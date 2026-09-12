"""股票研究专家。

该专家只负责把编排状态转换为 ``AnalysisRequest``，调用无状态研究流水线，
再把结构化结果投影回旧状态字段。取数、评分和行动结论均不交给 LLM。

多标的请求在**本专家内部**并行取数（DAG 只把整个股票任务当一个调度单元），
整批仍只构建一次快照，因此跨标的门禁（报告期混用）语义不受并行影响。
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from finance_agent.agents.base import AgentProtocol
from finance_agent.orchestrator.tools.stockdata import fetch_stock_data, search_candidates
from finance_agent.research.contracts import Action, AnalysisKind, AnalysisRequest
from finance_agent.research.legacy_adapter import project_legacy_many
from finance_agent.research.pipeline import ResearchPipeline
from finance_agent.research.request_parser import UnknownThemeError, parse_analysis_request
from finance_agent.research.rule_engine import RuleEngine
from finance_agent.research.snapshot_builder import production_builder
from finance_agent.research.screener import ThemeScreener
from finance_agent.research.theme_registry import ThemeRegistry, production_theme_registry
from finance_agent.research.theme_repository import PostgresThemeRepository

# 批次内并行取数上限：与候选上限一致，避免一次请求放大过多外部取数。
_MAX_FETCH_WORKERS = 5

logger = logging.getLogger(__name__)


class _FetchGateway:
    """生产环境网关：每次调用只取当前代码，避免跨请求共享股票数据。"""

    def get_security_data(self, stock_code: str) -> dict[str, Any]:
        return fetch_stock_data([stock_code]).get(stock_code, {})


class _InlineGateway:
    """编排层已提供数据时使用的只读网关。"""

    def __init__(self, data: dict[str, Any]):
        self._data = data

    def get_security_data(self, stock_code: str) -> dict[str, Any]:
        value = self._data.get(stock_code, {})
        return dict(value) if isinstance(value, dict) else {}


class _ThemeGateway(_FetchGateway):
    """主题筛选按成员逐只取数，复用生产行情网关。"""


class StockAnalysisAgent(AgentProtocol):
    """确定性股票研究专家，兼容旧的股票分析状态字段。"""

    agent_name = "stock_analysis"

    def __init__(
        self,
        checkpointer: Any = None,
        *,
        pipeline: ResearchPipeline | None = None,
        theme_screener: ThemeScreener | None = None,
        theme_registry: ThemeRegistry | None = None,
    ):
        # checkpointer 仅为旧编排构造签名保留，研究专家自身不持有会话状态。
        del checkpointer
        self._injected_pipeline = pipeline is not None
        self._pipeline = pipeline or ResearchPipeline(
            snapshot_builder=production_builder(_FetchGateway()),
            rule_engine=RuleEngine.default(),
        )
        self._theme_screener = theme_screener
        self._theme_registry = theme_registry

    def _registry(self) -> ThemeRegistry:
        if self._theme_registry is None:
            self._theme_registry = production_theme_registry()
        return self._theme_registry

    def _get_theme_screener(self) -> ThemeScreener:
        if self._theme_screener is None:
            from finance_agent.config import get_postgres_connection_factory
            self._theme_screener = ThemeScreener(
                PostgresThemeRepository(get_postgres_connection_factory()), _ThemeGateway(),
            )
        return self._theme_screener

    @staticmethod
    def _codes_from_state(state: dict[str, Any], message: str) -> list[str]:
        del message
        resolved = state.get("resolved_stocks", []) or []
        return [
            str(item.get("code"))
            for item in resolved
            if isinstance(item, dict) and item.get("code")
        ]

    def _resolve_candidate_codes(self, user_message: str) -> list[str]:
        """候选发现：主题代表股优先，其次名称/行业关键词搜索。

        默认 AKShare 股票列表不含 ``industry``，行业/主题口语词（"消费""白酒"）
        无法靠字段匹配命中；因此在主题注册表中显式维护的代表股先行，
        再由 ``search_candidates`` 处理"直接点名股票"等情形。
        """
        if not user_message.strip():
            return []
        representative = self._representative_codes(user_message)
        if representative:
            return representative
        try:
            raw = search_candidates.invoke({"user_query": user_message, "max_results": 5})
            candidates = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            return []
        if not isinstance(candidates, list):
            return []
        return list(dict.fromkeys(
            str(item.get("code", "")).strip()
            for item in candidates
            if isinstance(item, dict) and item.get("code")
        ))[:5]

    def _representative_codes(self, user_message: str) -> list[str]:
        """命中注册主题则返回其代表股；未命中或读路径不可用时返回空列表。"""
        try:
            entry = self._registry().match_in_text(user_message)
        except Exception:  # noqa: BLE001 - 注册表不可用不得阻断候选发现
            return []
        if entry is None:
            return []
        return list(dict.fromkeys(entry.representative_codes))[:5]

    def _pipeline_for_state(self, stock_data: dict[str, Any]) -> ResearchPipeline:
        if self._injected_pipeline:
            return self._pipeline
        if not stock_data:
            return self._pipeline
        return ResearchPipeline(
            snapshot_builder=production_builder(_InlineGateway(stock_data)),
            rule_engine=RuleEngine.default(),
        )

    @staticmethod
    def _status(results: list[Any]) -> str:
        """任一标的结论降级即视为本轮降级。"""
        return "degraded" if any(
            result.action is Action.INSUFFICIENT_DATA for result in results
        ) else "success"

    @staticmethod
    def _content(results: list[Any]) -> str:
        """逐条给出标的结论，比较请求不会只展示其中一只。"""
        return "\n".join(
            result.narrative or f"研究结论：{result.action.value}。" for result in results
        )

    def _resolve_request(self, state: dict[str, Any], message: str) -> tuple[AnalysisRequest | None, dict[str, Any] | None]:
        """把状态解析为研究请求；无法解析时返回结构化错误，不抛内部异常。"""
        profile = state.get("user_profile", {}) or {}
        try:
            request = parse_analysis_request(
                message,
                resolved_stocks=state.get("resolved_stocks", []) or [],
                intent_slots=state.get("intent_slots", {}) or {},
                user_profile=profile,
                theme_registry=self._registry(),
            )
        except UnknownThemeError as exc:
            # 未注册主题：改用该主题文本做候选搜索；无候选再澄清，不泄露内部异常。
            codes = self._resolve_candidate_codes(exc.theme_text)
            if not codes:
                return None, {
                    "content": f"主题筛选暂不可用：{exc.theme_text}",
                    "status": "degraded",
                    "clarification": (
                        f"未找到与「{exc.theme_text}」匹配的候选股票，请补充主题或直接提供股票代码。"
                    ),
                }
            return self._request_from_codes(state, profile, codes), None
        except ValueError as exc:
            can_discover_candidates = (
                str(state.get("current_task_intent", "")) == "stock_recommendation"
                and "单股分析必须且只能包含一只股票" in str(exc)
            )
            if not can_discover_candidates:
                # 请求形态非法（如单股请求带多只代码）。细节只进日志，
                # 用户侧给固定文案，避免内部校验文本外泄。
                logger.debug("股票请求解析失败 intent=%s error=%s",
                             state.get("current_task_intent"), exc)
                return None, {
                    "content": "股票研究暂不可用：请求无法识别，请明确提供股票名称或6位代码。",
                    "status": "degraded",
                    "clarification": None,
                }
            codes = self._resolve_candidate_codes(message)
            if not codes:
                return None, {
                    "content": "股票研究暂不可用：未找到匹配的候选股票。",
                    "status": "degraded",
                    "clarification": None,
                }
            return self._request_from_codes(state, profile, codes), None
        if request.kind.value == "theme_screening":
            return request, None
        if not request.stock_codes:
            return None, {"content": "股票研究暂不可用：未识别到股票代码", "status": "degraded", "clarification": None}
        return request, None

    @staticmethod
    def _request_from_codes(state: dict[str, Any], profile: dict[str, Any], codes: list[str]) -> AnalysisRequest:
        """把候选/多标的结果规范为运行级请求（多标的按比较形态承载，逐只出结论）。"""
        kind = AnalysisKind.SINGLE_STOCK if len(codes) == 1 else AnalysisKind.COMPARISON
        return AnalysisRequest(
            kind=kind,
            stock_codes=codes,
            profile_complete=bool(
                str(profile.get("risk_preference", "")).strip()
                and str(profile.get("holding_period", "")).strip()
            ),
        )

    def plan(self, state: dict[str, Any]) -> dict[str, Any]:
        """把状态解析为可扇出的执行计划，不执行分析、不取数。

        返回 ``{"kind": "fanout", "request": {...}}``（逐标的扇出）、
        ``{"kind": "defer"}``（主题筛选交给 task DAG）或
        ``{"kind": "error", "content": ..., "status": ..., "clarification": ...}``。
        """
        message = str(state.get("requirement", "") or state.get("user_message", ""))
        request, error = self._resolve_request(state, message)
        if error is not None:
            return {"kind": "error", **error}
        assert request is not None
        if request.kind.value == "theme_screening":
            return {"kind": "defer"}
        return {"kind": "fanout", "request": request.model_dump(mode="json")}

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        """解析一次状态并写回新旧两套结果，不保存本次调用数据。"""
        message = str(state.get("requirement", "") or state.get("user_message", ""))
        request, error = self._resolve_request(state, message)
        if error is not None:
            return self._failed(state, error)
        assert request is not None
        return self.run_resolved(state, request)

    def run_resolved(self, state: dict[str, Any], request: AnalysisRequest) -> dict[str, Any]:
        """对**已解析**请求执行研究（主题筛选或逐标的批量），写回兼容字段。

        图级逐标的扇出先把数据取好再汇入本方法，因此这里对整批请求只构建
        一次快照，跨标的门禁（报告期混用）语义保持不变。
        """
        profile = state.get("user_profile", {}) or {}
        stock_data = state.get("stock_data", {}) or {}

        try:
            if request.kind.value == "theme_screening":
                return self._run_theme_screening(state, request, profile)
            if not request.stock_codes:
                raise ValueError("未识别到股票代码")
            if not stock_data and not self._injected_pipeline:
                stock_data = self._fetch_stock_data_parallel(request.stock_codes, state)
                state["stock_data"] = stock_data
            pipeline = self._pipeline_for_state(stock_data)
            if hasattr(pipeline, "analyze_per_security"):
                results, facts = pipeline.analyze_per_security(request, user_profile=profile)
            else:
                results, facts = [pipeline.analyze(request, user_profile=profile)], []
        except Exception:  # noqa: BLE001 - 分析失败统一降级，细节只进日志
            # 该分支包裹取数/快照/评分/投影全过程：任何内部异常都不得把原始
            # 异常文本（校验信息、连接串等）暴露给用户，只给固定文案。
            logger.exception(
                "股票研究失败 intent=%s requirement=%s",
                state.get("current_task_intent"), state.get("requirement"),
            )
            return self._failed(state, {
                "content": "股票研究暂不可用，请稍后重试。",
                "status": "degraded",
                "clarification": None,
            })

        projected = project_legacy_many(results)
        for code, entry in projected["stock_analysis"].items():
            raw = stock_data.get(code, {}) if isinstance(stock_data, dict) else {}
            if isinstance(raw, dict):
                for key in ("quote", "basic_info", "search_candidate"):
                    if key in raw:
                        entry[key] = raw[key]
        state["stock_analysis"] = projected["stock_analysis"]
        state["technical_analysis"] = projected["technical_analysis"]
        state["analysis_results"] = projected["analysis_results"]
        # 运行级请求（比较请求含全部标的）单独留档，审计才能按一次运行归组重放。
        state["research_request"] = request.model_dump(mode="json")
        if facts:
            existing = state.get("facts", []) or []
            existing_ids = {fact.fact_id for fact in existing}
            state["facts"] = existing + [fact for fact in facts if fact.fact_id not in existing_ids]
        content = self._content(results)
        state["agent_response"] = content
        self._write_intent_result(state, content, self._status(results))
        return state

    def _fetch_stock_data_parallel(
        self, codes: list[str], state: dict[str, Any],
    ) -> dict[str, Any]:
        """批次内并行取数；每个标的完成即上报进度。

        取数是最重的 I/O（单只约 5 次工具调用），串行会让多标的比较/推荐明显变慢；
        DAG 只把整个股票任务当一个调度单元，因此并行放在专家内部。
        单个标的失败只让它缺数据（后续给"数据不足"结论），不牵连整批。
        """
        if len(codes) <= 1:
            if codes:
                self._emit_progress(state, f"正在获取 {codes[0]} 行情与财务数据")
            return fetch_stock_data(codes)

        merged: dict[str, Any] = {}
        workers = min(_MAX_FETCH_WORKERS, len(codes))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(fetch_stock_data, [code]): code for code in codes}
            for future in as_completed(futures):
                code = futures[future]
                self._emit_progress(state, f"正在获取 {code} 行情与财务数据")
                try:
                    merged.update(future.result() or {})
                except Exception:  # noqa: BLE001 - 单只失败不阻断整批
                    merged[code] = {}
        return merged

    @staticmethod
    def _emit_progress(state: dict[str, Any], message: str) -> None:
        """上报逐标的进度；回调由编排层写入状态，缺失时静默（测试/直接调用）。"""
        callback = state.get("progress_callback")
        if callable(callback):
            callback(message)

    def _run_theme_screening(
        self, state: dict[str, Any], request: AnalysisRequest, profile: dict[str, Any],
    ) -> dict[str, Any]:
        """主题筛选：只使用已审核有效成员，产出结构化候选与待核验线索。

        退回代表股的两个条件（都要求注册表已登记代表股）：
        - 治理库不可用（未配置 PostgreSQL，筛选器无法构造）；
        - 该主题**尚未有任何已审核有效成员**。
        代表股未经主题审核，因此按普通研究结论呈现并明确标注来源，
        绝不让它们冒充已审核的主题成员；若已有成员但覆盖不足，如实报告短缺。
        """
        try:
            screening = self._get_theme_screener().screen(request, profile)
        except Exception:  # noqa: BLE001 - 治理库不可用时退回代表股
            logger.warning("主题筛选器不可用，尝试退回代表股 theme_id=%s",
                           request.theme_id, exc_info=True)
            fallback = self._representative_request(request)
            if fallback is None:
                return self._failed(state, {
                    "content": "主题筛选暂不可用，请稍后重试。",
                    "status": "degraded",
                    "clarification": None,
                })
            return self._representative_response(state, request, fallback)

        if screening.status == "insufficient_active_coverage" and not screening.active_members:
            fallback = self._representative_request(request)
            if fallback is not None:
                return self._representative_response(state, request, fallback)

        payload = {
            "status": screening.status,
            "personalization_status": screening.personalization_status,
            "candidates": [candidate.__dict__ for candidate in screening.ranked_candidates],
            "pending_leads": screening.pending_leads,
            "request": request.model_dump(mode="json"),
            "active_members": screening.active_members,
            "exclusions": screening.exclusions,
        }
        state["theme_screening"] = payload
        state["theme_screening_status"] = screening.status
        state["theme_candidates"] = payload["candidates"]
        state["pending_leads"] = screening.pending_leads
        state["personalization_status"] = screening.personalization_status
        state["stock_analysis"] = {}
        state["technical_analysis"] = {}
        state["analysis_results"] = [
            item.model_dump(mode="json") for item in screening.analysis_results
        ]
        if screening.facts:
            existing = state.get("facts", []) or []
            existing_ids = {fact.fact_id for fact in existing}
            state["facts"] = existing + [
                fact for fact in screening.facts if fact.fact_id not in existing_ids
            ]
        content = (
            "主题候选研究已完成。"
            if screening.status == "complete"
            else f"主题候选暂不可完整生成：{screening.status}。"
        )
        state["agent_response"] = content
        self._write_intent_result(state, content, "success" if screening.status == "complete" else "degraded")
        return state

    def _representative_response(
        self, state: dict[str, Any], request: AnalysisRequest, fallback: AnalysisRequest,
    ) -> dict[str, Any]:
        """以主题代表股出研究结论，并明确标注其未经主题审核。"""
        result_state = self.run_resolved(state, fallback)
        result_state["agent_response"] = (
            f"该主题暂无已审核有效成员，以下为「{request.theme_id}」的代表股研究结论"
            f"（未经主题审核，仅供参考）：\n{result_state.get('agent_response', '')}"
        )
        result_state["theme_screening"] = {
            "status": "representative_fallback",
            "personalization_status": "research_candidate",
            "candidates": [], "pending_leads": [],
            "request": request.model_dump(mode="json"),
            "active_members": [], "exclusions": [],
        }
        result_state["theme_screening_status"] = "representative_fallback"
        self._write_intent_result(result_state, result_state["agent_response"], "success")
        return result_state

    def _representative_request(self, request: AnalysisRequest) -> AnalysisRequest | None:
        """取该主题注册的代表股，构造逐只出结论的研究请求；未注册则返回 None。"""
        theme_id = request.theme_id
        if not theme_id:
            return None
        try:
            entries = self._registry().list_themes()
        except Exception:  # noqa: BLE001
            return None
        entry = next((item for item in entries if item.theme_id == theme_id), None)
        codes = list(entry.representative_codes) if entry is not None else []
        if not codes:
            return None
        kind = AnalysisKind.SINGLE_STOCK if len(codes) == 1 else AnalysisKind.COMPARISON
        return AnalysisRequest(
            kind=kind, stock_codes=codes,
            indicators=list(request.indicators), profile_complete=request.profile_complete,
        )

    @staticmethod
    def _failed(state: dict[str, Any], error: dict[str, Any]) -> dict[str, Any]:
        """统一的失败/降级写回；澄清问题与用户文案分离，不泄露内部异常。"""
        state["stock_analysis"] = {}
        state["technical_analysis"] = {}
        state["analysis_results"] = []
        clarification = error.get("clarification")
        if clarification:
            state["clarification_question"] = clarification
        content = str(error.get("content", "股票研究暂不可用。"))
        StockAnalysisAgent._write_intent_result(state, content, str(error.get("status", "degraded")))
        state["agent_response"] = content
        return state

    @staticmethod
    def _write_intent_result(state: dict[str, Any], content: str, status: str) -> None:
        payload = {"status": status, "content": content}
        intent = str(state.get("current_task_intent", "")).strip()
        targets = [intent] if intent in {"stock_analysis", "stock_recommendation"} else ["stock_analysis"]
        results = state.setdefault("intent_results", {})
        for target in targets:
            results[target] = payload.copy()

    def handle_single_stock(
        self,
        code: str,
        user_message: str = "",
        memory_context: str = "",
        chat_history: list[dict] | None = None,
        stock_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """保留旧调用入口，但内部仍走确定性流水线。"""
        del user_message, memory_context, chat_history
        data = stock_data or fetch_stock_data([code])
        request = AnalysisRequest(kind="single_stock", stock_codes=[code])
        result = self._pipeline_for_state(data).analyze(request, user_profile={})
        entry = project_legacy_many([result])["stock_analysis"].get(code, {"code": code})
        raw = data.get(code, {}) if isinstance(data, dict) else {}
        if isinstance(raw, dict):
            for key in ("quote", "basic_info", "search_candidate"):
                if key in raw:
                    entry[key] = raw[key]
        return entry

    def _direct_technical_analysis(self, *args: Any, **kwargs: Any) -> None:
        """旧调用方的兼容钩子；技术指标由快照/规则层统一处理。"""
        del args, kwargs
        return None
