"""股票研究专家。

该专家只负责把编排状态转换为 ``AnalysisRequest``，调用无状态研究流水线，
再把结构化结果投影回旧状态字段。取数、评分和行动结论均不交给 LLM。
"""

from __future__ import annotations

import json
from typing import Any

from finance_agent.agents.base import AgentProtocol
from finance_agent.orchestrator.tools.stockdata import fetch_stock_data, search_candidates
from finance_agent.research.contracts import Action, AnalysisRequest
from finance_agent.research.legacy_adapter import project_legacy
from finance_agent.research.pipeline import ResearchPipeline
from finance_agent.research.request_parser import parse_analysis_request
from finance_agent.research.rule_engine import RuleEngine
from finance_agent.research.snapshot_builder import SnapshotBuilder


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


class StockAnalysisAgent(AgentProtocol):
    """确定性股票研究专家，兼容旧的股票分析状态字段。"""

    agent_name = "stock_analysis"

    def __init__(
        self,
        checkpointer: Any = None,
        *,
        pipeline: ResearchPipeline | None = None,
    ):
        # checkpointer 仅为旧编排构造签名保留，研究专家自身不持有会话状态。
        del checkpointer
        self._injected_pipeline = pipeline is not None
        self._pipeline = pipeline or ResearchPipeline(
            snapshot_builder=SnapshotBuilder(_FetchGateway()),
            rule_engine=RuleEngine.default(),
        )

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
        """候选发现仍可使用外部数据，但发现结果必须经过同一研究流水线。"""
        if not user_message.strip():
            return []
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

    def _pipeline_for_state(self, stock_data: dict[str, Any]) -> ResearchPipeline:
        if self._injected_pipeline:
            return self._pipeline
        if not stock_data:
            return self._pipeline
        return ResearchPipeline(
            snapshot_builder=SnapshotBuilder(_InlineGateway(stock_data)),
            rule_engine=RuleEngine.default(),
        )

    @staticmethod
    def _status(result: Any) -> str:
        return "degraded" if result.action is Action.INSUFFICIENT_DATA else "success"

    @staticmethod
    def _content(result: Any) -> str:
        return result.narrative or f"研究结论：{result.action.value}。"

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        """解析一次状态并写回新旧两套结果，不保存本次调用数据。"""
        message = str(state.get("requirement", "") or state.get("user_message", ""))
        profile = state.get("user_profile", {}) or {}
        stock_data = state.get("stock_data", {}) or {}
        codes = self._codes_from_state(state, message)
        if not codes and str(state.get("current_task_intent", "")) == "stock_recommendation":
            codes = self._resolve_candidate_codes(message)
            if codes:
                state["resolved_stocks"] = [{"code": code} for code in codes]

        try:
            request = parse_analysis_request(
                message,
                resolved_stocks=state.get("resolved_stocks", []) or [],
                intent_slots=state.get("intent_slots", {}) or {},
                user_profile=profile,
            )
            if not request.stock_codes:
                raise ValueError("未识别到股票代码")
            if not stock_data and not self._injected_pipeline:
                stock_data = fetch_stock_data(request.stock_codes)
                state["stock_data"] = stock_data
            pipeline = self._pipeline_for_state(stock_data)
            if hasattr(pipeline, "analyze_with_facts"):
                result, facts = pipeline.analyze_with_facts(request, user_profile=profile)
            else:
                result = pipeline.analyze(request, user_profile=profile)
                facts = []
        except Exception as exc:
            state["stock_analysis"] = {}
            state["technical_analysis"] = {}
            state["analysis_results"] = []
            content = f"股票研究暂不可用：{exc}"
            self._write_intent_result(state, content, "degraded")
            state["agent_response"] = content
            return state

        projected = project_legacy(result)
        for code, entry in projected["stock_analysis"].items():
            raw = stock_data.get(code, {}) if isinstance(stock_data, dict) else {}
            if isinstance(raw, dict):
                for key in ("quote", "basic_info", "search_candidate"):
                    if key in raw:
                        entry[key] = raw[key]
        state["stock_analysis"] = projected["stock_analysis"]
        state["technical_analysis"] = projected["technical_analysis"]
        state["analysis_results"] = projected["analysis_results"]
        if facts:
            existing = state.get("facts", []) or []
            existing_ids = {fact.fact_id for fact in existing}
            state["facts"] = existing + [fact for fact in facts if fact.fact_id not in existing_ids]
        content = self._content(result)
        state["agent_response"] = content
        self._write_intent_result(state, content, self._status(result))
        return state

    @staticmethod
    def _write_intent_result(state: dict[str, Any], content: str, status: str) -> None:
        payload = {"status": status, "content": content}
        intent = str(state.get("current_task_intent", "")).strip()
        targets = [intent] if intent in {"market_query", "stock_recommendation"} else ["market_query"]
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
        entry = project_legacy(result)["stock_analysis"].get(code, {"code": code})
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
