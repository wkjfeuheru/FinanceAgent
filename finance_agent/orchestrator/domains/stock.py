"""股票研究领域子图与确定性操作（设计 §6.4）。

从 ``StockAnalysisAgent`` 抽取：请求解析、候选发现、逐标的并行取数、研究流水线
调用、技术指标展示与主题筛选。取数、评分与结论全部由确定性 pipeline 完成。
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable

from finance_agent.orchestrator.contracts import (
    DEGRADED_INTENT_STATUSES,
    AsyncJobRef,
    BusinessDomain,
    DomainTaskContext,
)
from finance_agent.orchestrator.domains.base import (
    DomainOperation,
    OperationResult,
    build_domain_graph,
    context_text,
    keyword_mode,
    merge_facts,
)
from finance_agent.orchestrator.params import intent_slots_for
from finance_agent.research.contracts import (
    Action,
    AnalysisKind,
    AnalysisRequest,
    SingleStockShapeError,
)
from finance_agent.research.legacy_adapter import project_legacy_many
from finance_agent.research.pipeline import ResearchPipeline
from finance_agent.research.request_parser import UnknownThemeError, parse_analysis_request
from finance_agent.research.rule_engine import RuleEngine
from finance_agent.research.snapshot_builder import production_builder
from finance_agent.research.screener import ThemeScreener
from finance_agent.research.theme_registry import production_theme_registry
from finance_agent.research.theme_repository import PostgresThemeRepository

logger = logging.getLogger(__name__)

_MAX_FETCH_WORKERS = 5
_MIN_TECHNICAL_BARS = 60

# A 股 6 位代码（与原 SlotExtractor 一致的口径）。
_VALID_CODE_RE = re.compile(r"(?<!\d)(?:60\d{4}|00\d{4}|30\d{4}|68\d{4}|8\d{5}|4\d{5})(?!\d)")


def _codes_in_text(message: str) -> list[str]:
    """提取消息中的 A 股 6 位代码（去重、保序）。"""
    return list(dict.fromkeys(_VALID_CODE_RE.findall(message or "")))

_MODE_KEYWORDS = {
    "theme_screening": ("主题", "板块", "概念", "龙头", "题材"),
    "candidate_search": ("推荐", "选股", "筛选", "候选", "有哪些"),
}


class _FetchGateway:
    """生产环境网关：每次调用只取当前代码，避免跨请求共享股票数据。"""

    def __init__(self, fetch: Callable[..., dict[str, Any]] | None = None) -> None:
        self._fetch = fetch

    def get_security_data(self, stock_code: str) -> dict[str, Any]:
        fetch = self._fetch or _default_fetch()
        return fetch([stock_code]).get(stock_code, {})


class _InlineGateway:
    """编排层已提供数据时使用的只读网关。"""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def get_security_data(self, stock_code: str) -> dict[str, Any]:
        value = self._data.get(stock_code, {})
        return dict(value) if isinstance(value, dict) else {}


class _ThemeGateway(_FetchGateway):
    """主题筛选按成员逐只取数，复用生产行情网关。"""


@dataclass
class StockDeps:
    """股票领域确定性依赖；可注入 pipeline / 主题组件 / 取数函数。"""

    pipeline: Any = None
    injected_pipeline: bool = False
    theme_screener: Any = None
    theme_registry: Any = None
    fetch: Callable[..., dict[str, Any]] | None = None
    candidate_search: Any = None
    emit_progress: Callable[[dict[str, Any], str], None] | None = None
    # CPU 密集技术指标可卸载到 QuantGateway；None 表示在线内联计算。
    quant_gateway: Any = None
    quant_wait_seconds: float = 0.0
    defaults: list[Any] = field(default_factory=list)


def _default_fetch() -> Callable[..., dict[str, Any]]:
    from finance_agent.orchestrator.tools.stockdata import fetch_stock_data

    return fetch_stock_data


def _default_search_candidates() -> Any:
    from finance_agent.orchestrator.tools.stockdata import search_candidates

    return search_candidates


def _search(deps: StockDeps) -> Any:
    return deps.candidate_search if deps.candidate_search is not None else _default_search_candidates()


def _default_pipeline(deps: StockDeps) -> Any:
    if deps.pipeline is not None:
        return deps.pipeline
    return ResearchPipeline(
        snapshot_builder=production_builder(_FetchGateway(deps.fetch)),
        rule_engine=RuleEngine.default(),
    )


def default_stock_deps() -> StockDeps:
    return StockDeps()


def registry(deps: StockDeps) -> Any:
    if deps.theme_registry is None:
        deps.theme_registry = production_theme_registry()
    return deps.theme_registry


def get_theme_screener(deps: StockDeps) -> Any:
    if deps.theme_screener is None:
        from finance_agent.config import get_postgres_connection_factory

        deps.theme_screener = ThemeScreener(
            PostgresThemeRepository(get_postgres_connection_factory()),
            _ThemeGateway(deps.fetch),
        )
    return deps.theme_screener


def pipeline_for_state(deps: StockDeps, stock_data: dict[str, Any]) -> Any:
    if deps.injected_pipeline and deps.pipeline is not None:
        return deps.pipeline
    if not stock_data:
        return _default_pipeline(deps)
    return ResearchPipeline(
        snapshot_builder=production_builder(_InlineGateway(stock_data)),
        rule_engine=RuleEngine.default(),
    )


def representative_codes(deps: StockDeps, user_message: str) -> list[str]:
    try:
        entry = registry(deps).match_in_text(user_message)
    except Exception:  # noqa: BLE001 - 注册表不可用不得阻断候选发现
        return []
    if entry is None:
        return []
    return list(dict.fromkeys(entry.representative_codes))[:5]


def resolve_candidate_codes(deps: StockDeps, user_message: str) -> list[str]:
    """候选发现：主题代表股优先，其次名称/行业关键词搜索。"""
    if not user_message.strip():
        return []
    representative = representative_codes(deps, user_message)
    if representative:
        return representative
    try:
        raw = _search(deps).invoke({"user_query": user_message, "max_results": 5})
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


def request_from_codes(profile: dict[str, Any], codes: list[str]) -> AnalysisRequest:
    kind = AnalysisKind.SINGLE_STOCK if len(codes) == 1 else AnalysisKind.COMPARISON
    return AnalysisRequest(
        kind=kind,
        stock_codes=codes,
        profile_complete=bool(
            str(profile.get("risk_preference", "")).strip()
            and str(profile.get("holding_period", "")).strip()
        ),
    )


def resolve_named_stock_code(deps: StockDeps, message: str) -> list[str]:
    """把消息中的股票**名称**解析为代码（确定性最佳匹配）。

    旧编排由已退役的 SlotExtractor 负责名称→代码；V2 单领域直达必须自行补齐，
    否则"分析贵州茅台"这类只有名称、没有 6 位代码的请求会被判为无法识别。
    只接受**名称与代码可对应**的候选，避免把无关结果当成本轮标的。
    """
    if not message.strip():
        return []
    try:
        raw = _search(deps).invoke({"user_query": message, "max_results": 5})
        candidates = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return []
    if not isinstance(candidates, list):
        return []

    named: list[str] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code", "")).strip()
        name = str(item.get("name", "")).strip()
        # 候选的名称必须真的出现在消息里，才算本轮提及的标的。
        if code and name and name in message:
            if code not in named:
                named.append(code)
    return named[:5]


def _unrecognizable_request() -> dict[str, Any]:
    """统一的"请求无法识别"降级响应；不泄露内部校验细节。"""
    return {
        "content": "股票研究暂不可用：请求无法识别，请明确提供股票名称或6位代码。",
        "status": "degraded",
        "clarification": None,
    }


def resolve_stock_request(
    deps: StockDeps, state: dict[str, Any], message: str,
) -> tuple[AnalysisRequest | None, dict[str, Any] | None]:
    """把状态解析为研究请求；无法解析时返回结构化错误，不抛内部异常。"""
    profile = state.get("user_profile", {}) or {}
    try:
        request = parse_analysis_request(
            message,
            resolved_stocks=state.get("resolved_stocks", []) or [],
            intent_slots=state.get("intent_slots", {}) or {},
            user_profile=profile,
            theme_registry=registry(deps),
        )
    except UnknownThemeError as exc:
        codes = resolve_candidate_codes(deps, exc.theme_text)
        if not codes:
            return None, {
                "content": f"主题筛选暂不可用：{exc.theme_text}",
                "status": "degraded",
                "clarification": (
                    f"未找到与「{exc.theme_text}」匹配的候选股票，请补充主题或直接提供股票代码。"
                ),
            }
        return request_from_codes(profile, codes), None
    except ValueError as exc:
        # 请求形态不合法：单股请求必须恰好一只代码。按意图决定补救方式：
        # - stock_recommendation：走候选发现（代表股优先，其次关键词搜索）；
        # - stock_analysis：消息里只有股票名称（无 6 位代码）时，用名称→代码补齐。
        # 判定按**异常类型**而非报错文案：文案优化不应让补救逻辑静默失效，
        # 其它 ValueError（如比较请求股票不足）也不会被误判为单股形态错误。
        single_stock_shape_error = isinstance(exc, SingleStockShapeError)
        intent = str(state.get("current_task_intent", ""))
        if single_stock_shape_error and intent == "stock_recommendation":
            codes = resolve_candidate_codes(deps, message)
            if not codes:
                return None, {
                    "content": "股票研究暂不可用：未找到匹配的候选股票。",
                    "status": "degraded",
                    "clarification": None,
                }
            return request_from_codes(profile, codes), None
        if single_stock_shape_error and not _codes_in_text(message):
            named_codes = resolve_named_stock_code(deps, message)
            if named_codes:
                return request_from_codes(profile, named_codes), None
            return None, {
                "content": "股票研究暂不可用：未识别到股票名称或代码，请提供股票名称或6位代码。",
                "status": "degraded",
                "clarification": "未找到与您提到的名称匹配的股票，请补充股票名称或6位代码。",
            }
        logger.debug("股票请求解析失败 intent=%s error=%s",
                     state.get("current_task_intent"), exc)
        return None, _unrecognizable_request()
    if request.kind.value == "theme_screening":
        return request, None
    if not request.stock_codes:
        return None, {
            "content": "股票研究暂不可用：未识别到股票代码",
            "status": "degraded",
            "clarification": None,
        }
    return request, None


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def compute_technical_indicators(
    stock_data: Any, codes: Any, analysis_type: str = "both",
) -> dict[str, Any]:
    """为请求内的标的计算展示层技术指标（不写证据、不参与评分）。"""
    from finance_agent.orchestrator.tools.technical import compute_all_indicators

    result: dict[str, Any] = {}
    if analysis_type == "fundamental" or not isinstance(stock_data, dict):
        return result
    for code in codes or []:
        series = _technical_series(stock_data, code)
        if series is None:
            continue
        high, low, close = series
        try:
            result[code] = compute_all_indicators(high, low, close)
        except Exception:  # noqa: BLE001 - 指标计算失败只跳过该标的
            logger.warning("技术指标计算失败 code=%s", code, exc_info=True)
    return result


def _technical_series(stock_data: Any, code: str) -> tuple[list[float], list[float], list[float]] | None:
    raw = stock_data.get(code)
    history = raw.get("history") if isinstance(raw, dict) else None
    rows = history.get("data") if isinstance(history, dict) else None
    if not isinstance(rows, list) or len(rows) < _MIN_TECHNICAL_BARS:
        return None
    close: list[float] = []
    high: list[float] = []
    low: list[float] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        c, h, low_value = (
            _as_float(row.get("close")),
            _as_float(row.get("high")),
            _as_float(row.get("low")),
        )
        if c is None or h is None or low_value is None:
            continue
        close.append(c)
        high.append(h)
        low.append(low_value)
    if len(close) < _MIN_TECHNICAL_BARS:
        return None
    return high, low, close


def compute_technical_via_gateway(
    deps: StockDeps,
    stock_data: Any,
    codes: Any,
    analysis_type: str = "both",
    *,
    context: DomainTaskContext | None = None,
) -> tuple[dict[str, Any], bool, list[tuple[str, AsyncJobRef]]]:
    """经 QuantGateway 卸载技术指标计算。

    返回 ``(indicators, pending, pending_jobs)``：``pending=True`` 表示任务仍在
    预算内未完成，调用方应把 ``pending_jobs``（``(标的代码, AsyncJobRef)`` 对，
    代码用于恢复时把指标合并回 ``technical_analysis[code]``）写入结论并中断图
    （``awaiting_quant``），不得伪造结果。

    ``context`` 提供 customer_id/thread_id/run_id/领域 task_id，使 Celery 网关
    能把 job 引用落库（幂等、可授权查询），状态端点随后可据此恢复原会话。
    """
    if analysis_type == "fundamental" or not isinstance(stock_data, dict):
        return {}, False, []
    gateway = deps.quant_gateway
    indicators: dict[str, Any] = {}
    pending_jobs: list[tuple[str, AsyncJobRef]] = []
    submit_kwargs: dict[str, str] = {}
    if context is not None:
        submit_kwargs = {
            "customer_id": str(context.customer_id),
            "thread_id": str(context.thread_id),
            "run_id": str(context.run_id),
            "task_id": str(context.task.task_id),
        }
    for code in codes or []:
        series = _technical_series(stock_data, code)
        if series is None:
            continue
        high, low, close = series
        ref = gateway.submit(
            "technical_indicators",
            {"high": high, "low": low, "close": close},
            f"technical_indicators:{code}",
            **submit_kwargs,
        )
        pending_jobs.append((str(code), ref))
        if _wait_for_job(gateway, ref.job_id, deps.quant_wait_seconds):
            result = gateway.result(ref.job_id) or {}
            indicators[code] = result.get("indicators", {})
            pending_jobs.pop()
        else:
            return indicators, True, pending_jobs
    return indicators, False, pending_jobs


def _wait_for_job(gateway: Any, job_id: str, budget_seconds: float) -> bool:
    import time

    deadline = time.monotonic() + max(0.0, budget_seconds)
    while True:
        status = gateway.status(job_id)
        if status == "completed":
            return True
        if status in {"failed", "cancelled"}:
            return False
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


def _emit_progress(deps: StockDeps, state: dict[str, Any], message: str) -> None:
    callback = state.get("progress_callback")
    if callable(callback):
        callback(message)
    elif deps.emit_progress is not None:
        deps.emit_progress(state, message)


def fetch_stock_data_parallel(
    deps: StockDeps, codes: list[str], state: dict[str, Any],
) -> dict[str, Any]:
    fetch = deps.fetch or _default_fetch()
    if len(codes) <= 1:
        if codes:
            _emit_progress(deps, state, f"正在获取 {codes[0]} 行情与财务数据")
        return fetch(codes)

    merged: dict[str, Any] = {}
    workers = min(_MAX_FETCH_WORKERS, len(codes))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch, [code]): code for code in codes}
        for future in as_completed(futures):
            code = futures[future]
            _emit_progress(deps, state, f"正在获取 {code} 行情与财务数据")
            try:
                merged.update(future.result() or {})
            except Exception:  # noqa: BLE001 - 单只失败不阻断整批
                merged[code] = {}
    return merged


def write_intent_result(state: dict[str, Any], content: str, status: str) -> None:
    payload = {"status": status, "content": content}
    intent = str(state.get("current_task_intent", "")).strip()
    targets = [intent] if intent in {"stock_analysis", "stock_recommendation"} else ["stock_analysis"]
    results = state.setdefault("intent_results", {})
    for target in targets:
        results[target] = payload.copy()


def failed(state: dict[str, Any], error: dict[str, Any]) -> dict[str, Any]:
    """统一的失败/降级写回；澄清问题与用户文案分离，不泄露内部异常。"""
    state["stock_analysis"] = {}
    state["technical_analysis"] = {}
    state["analysis_results"] = []
    clarification = error.get("clarification")
    if clarification:
        state["clarification_question"] = clarification
    content = str(error.get("content", "股票研究暂不可用。"))
    write_intent_result(state, content, str(error.get("status", "degraded")))
    state["agent_response"] = content
    return state


def _status(results: list[Any]) -> str:
    return "degraded" if any(
        result.action is Action.INSUFFICIENT_DATA for result in results
    ) else "success"


def _content(results: list[Any]) -> str:
    return "\n".join(
        result.narrative or f"研究结论：{result.action.value}。" for result in results
    )


def representative_request(deps: StockDeps, request: AnalysisRequest) -> AnalysisRequest | None:
    theme_id = request.theme_id
    if not theme_id:
        return None
    try:
        entries = registry(deps).list_themes()
    except Exception:  # noqa: BLE001
        return None
    entry = next((item for item in entries if item.theme_id == theme_id), None)
    codes = list(entry.representative_codes) if entry is not None else []
    if not codes:
        return None
    kind = AnalysisKind.SINGLE_STOCK if len(codes) == 1 else AnalysisKind.COMPARISON
    return AnalysisRequest(
        kind=kind, stock_codes=codes,
        analysis_type=request.analysis_type, profile_complete=request.profile_complete,
    )


def run_resolved(deps: StockDeps, state: dict[str, Any], request: AnalysisRequest) -> dict[str, Any]:
    """对已解析请求执行研究（主题筛选或逐标的批量），写回兼容字段。"""
    profile = state.get("user_profile", {}) or {}
    stock_data = state.get("stock_data", {}) or {}

    try:
        if request.kind.value == "theme_screening":
            return _run_theme_screening(deps, state, request, profile)
        if not request.stock_codes:
            raise ValueError("未识别到股票代码")
        if not stock_data and not deps.injected_pipeline:
            stock_data = fetch_stock_data_parallel(deps, request.stock_codes, state)
            state["stock_data"] = stock_data
        pipeline = pipeline_for_state(deps, stock_data)
        if hasattr(pipeline, "analyze_per_security"):
            results, facts = pipeline.analyze_per_security(request, user_profile=profile)
        else:
            results, facts = [pipeline.analyze(request, user_profile=profile)], []
    except Exception:  # noqa: BLE001 - 分析失败统一降级，细节只进日志
        logger.exception(
            "股票研究失败 intent=%s requirement=%s",
            state.get("current_task_intent"), state.get("requirement"),
        )
        return failed(state, {
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
    state["technical_analysis"] = compute_technical_indicators(
        stock_data, request.stock_codes, request.analysis_type,
    )
    state["analysis_results"] = projected["analysis_results"]
    state["research_request"] = request.model_dump(mode="json")
    if facts:
        state["facts"] = merge_facts(state.get("facts", []) or [], facts)
    content = _content(results)
    state["agent_response"] = content
    write_intent_result(state, content, _status(results))
    return state


def _run_theme_screening(
    deps: StockDeps, state: dict[str, Any], request: AnalysisRequest, profile: dict[str, Any],
) -> dict[str, Any]:
    try:
        screening = get_theme_screener(deps).screen(request, profile)
    except Exception:  # noqa: BLE001 - 治理库不可用时退回代表股
        logger.warning("主题筛选器不可用，尝试退回代表股 theme_id=%s",
                       request.theme_id, exc_info=True)
        fallback = representative_request(deps, request)
        if fallback is None:
            return failed(state, {
                "content": "主题筛选暂不可用，请稍后重试。",
                "status": "degraded",
                "clarification": None,
            })
        return _representative_response(deps, state, request, fallback)

    if screening.status == "insufficient_active_coverage" and not screening.active_members:
        fallback = representative_request(deps, request)
        if fallback is not None:
            return _representative_response(deps, state, request, fallback)

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
        state["facts"] = merge_facts(state.get("facts", []) or [], screening.facts)
    content = (
        "主题候选研究已完成。"
        if screening.status == "complete"
        else f"主题候选暂不可完整生成：{screening.status}。"
    )
    state["agent_response"] = content
    write_intent_result(state, content, "success" if screening.status == "complete" else "degraded")
    return state


def _representative_response(
    deps: StockDeps, state: dict[str, Any], request: AnalysisRequest, fallback: AnalysisRequest,
) -> dict[str, Any]:
    result_state = run_resolved(deps, state, fallback)
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
    write_intent_result(result_state, result_state["agent_response"], "success")
    return result_state


def invoke_stock(deps: StockDeps, state: dict[str, Any]) -> dict[str, Any]:
    message = str(state.get("requirement", "") or state.get("user_message", ""))
    request, error = resolve_stock_request(deps, state, message)
    if error is not None:
        return failed(state, error)
    assert request is not None
    return run_resolved(deps, state, request)


def handle_single_stock(
    deps: StockDeps, code: str, stock_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fetch = deps.fetch or _default_fetch()
    data = stock_data or fetch([code])
    request = AnalysisRequest(kind="single_stock", stock_codes=[code])
    result = pipeline_for_state(deps, data).analyze(request, user_profile={})
    entry = project_legacy_many([result])["stock_analysis"].get(code, {"code": code})
    raw = data.get(code, {}) if isinstance(data, dict) else {}
    if isinstance(raw, dict):
        for key in ("quote", "basic_info", "search_candidate"):
            if key in raw:
                entry[key] = raw[key]
    return entry


def _resolve_stock_mode(context: DomainTaskContext) -> str:
    goal = context.task.goal or ""
    if str(context.task.instruction or "").strip():
        goal = f"{goal} {context.task.instruction}"
    return keyword_mode(goal, _MODE_KEYWORDS, "single_analysis")


def _stock_research(deps: StockDeps, context: DomainTaskContext) -> OperationResult:
    # 领域内的 goal→意图映射：推荐/主题类请求必须走 stock_recommendation，
    # 否则候选发现（代表股优先、其次关键词搜索）不会触发，只会报"请求无法识别"。
    mode = _resolve_stock_mode(context)
    intent = "stock_recommendation" if mode in {"candidate_search", "theme_screening"} else "stock_analysis"
    params = dict(getattr(context, "params", {}) or {})
    state: dict[str, Any] = {
        "requirement": context.task.goal,
        "user_message": context.user_message,
        "current_task_intent": intent,
        "intent_results": {},
        # 根图抽取到的参数（分析维度/代码/主题）与用户画像卡：此前硬编码为空，
        # 使 profile_complete 恒假、个性化结论不可达。
        "intent_slots": intent_slots_for(BusinessDomain.STOCK_RESEARCH, params),
        "user_profile": dict(getattr(context, "user_profile", {}) or {}),
        "facts": [],
    }
    result_state = invoke_stock(deps, state)
    structured = {
        "stock_data": result_state.get("stock_data", {}) or {},
        "stock_analysis": result_state.get("stock_analysis", {}) or {},
        "technical_analysis": result_state.get("technical_analysis", {}) or {},
        "analysis_results": result_state.get("analysis_results", []) or [],
        "theme_screening": result_state.get("theme_screening", {}) or {},
        "theme_screening_status": result_state.get("theme_screening_status", "") or "",
        "theme_candidates": result_state.get("theme_candidates", []) or [],
        "pending_leads": result_state.get("pending_leads", []) or [],
        "personalization_status": result_state.get("personalization_status", "") or "",
        "research_request": result_state.get("research_request"),
        "facts": [
            fact.model_dump(mode="json")
            for fact in result_state.get("facts", []) or []
            if hasattr(fact, "model_dump")
        ],
    }
    summary = str(result_state.get("agent_response", "") or "")
    intent_results = result_state.get("intent_results", {}) or {}
    status = "success"
    for payload in intent_results.values():
        if isinstance(payload, dict) and payload.get("status") in DEGRADED_INTENT_STATUSES:
            status = "partial"
            break
    limitations = [str(result_state.get("clarification_question"))] if result_state.get("clarification_question") else []

    # CPU 密集技术指标：若已配置 QuantGateway，则卸载并支持异步中断。
    if deps.quant_gateway is not None:
        codes = [code for code in (result_state.get("stock_analysis", {}) or {})]
        try:
            indicators, pending, pending_jobs = compute_technical_via_gateway(
                deps, structured["stock_data"], codes, context=context,
            )
        except Exception:  # noqa: BLE001 - 网关异常不阻断研究结论
            logger.warning("quant gateway 技术指标失败", exc_info=True)
        else:
            if indicators:
                structured["technical_analysis"] = indicators
            if pending:
                # 把实际提交的 AsyncJobRef 写进结论：上层据此写入 pending_jobs、
                # 端点按真实 Celery job_id 授权查询并恢复原会话。codes 记录每个
                # job 对应的标的，恢复时把指标合并回 technical_analysis[code]。
                structured["pending_jobs"] = [
                    ref.model_dump(mode="json") for _, ref in pending_jobs
                ]
                structured["pending_job_codes"] = {
                    ref.job_id: code for code, ref in pending_jobs
                }
                return OperationResult(
                    structured_data=structured,
                    summary=summary,
                    status="processing",
                    limitations=[*limitations, "awaiting_quant"],
                    pending_jobs=[ref for _, ref in pending_jobs],
                )

    return OperationResult(structured_data=structured, summary=summary, status=status, limitations=limitations)


def default_stock_operations(deps: StockDeps) -> list[DomainOperation]:
    modes = frozenset({"single_analysis", "theme_screening", "candidate_search"})
    return [
        DomainOperation(
            name="stock_research",
            modes=modes,
            handler=lambda context: _stock_research(deps, context),
        )
    ]


def build_stock_domain_graph(deps: StockDeps | None = None, *, operations=None):
    """编译股票领域子图；白名单来自 operation 注册表（唯一事实源）。

    ``operations=[]`` 是合法输入（白名单为空），用 ``is None`` 判缺省。
    """
    from finance_agent.orchestrator.operations import default_operation_registry

    registry = default_operation_registry()
    return build_domain_graph(
        BusinessDomain.STOCK_RESEARCH,
        default_stock_operations(deps) if operations is None else operations,
        default_mode=registry.spec(BusinessDomain.STOCK_RESEARCH).default_mode,
        mode_resolver=registry.spec(BusinessDomain.STOCK_RESEARCH).mode_resolver,
    )


__all__ = [
    "StockDeps",
    "build_stock_domain_graph",
    "compute_technical_indicators",
    "default_stock_deps",
    "default_stock_operations",
    "handle_single_stock",
    "invoke_stock",
    "run_resolved",
]
