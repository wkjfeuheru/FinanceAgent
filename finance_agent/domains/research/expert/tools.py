"""股票研究专家的取数辅助与技术指标工具（无确定性研究管线）。"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from finance_agent.shared import name_matching as name_match
from finance_agent.orchestration.experts.base import sink_of
from finance_agent.domains.research.expert import stockdata as _stockdata

logger = logging.getLogger(__name__)

STOCK_UNAVAILABLE = "股票研究暂不可用，请稍后重试。"
_MIN_TECHNICAL_BARS = 60


def _lookup_items(message: str, max_results: int = 5) -> tuple[list[dict[str, Any]], list[str]]:
    payload = {"user_query": message, "max_results": max_results}
    raw = _stockdata.match_stock_names.invoke(payload)  # type: ignore[attr-defined]
    parsed: Any = raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return [], []
    if isinstance(parsed, dict):
        items = parsed.get("candidates") or parsed.get("data") or []
        ambiguous = [str(token) for token in parsed.get("ambiguous_tokens") or []]
    else:
        items = parsed
        ambiguous = []
    if not isinstance(items, list):
        return [], []
    return [item for item in items if isinstance(item, dict)], ambiguous


@tool
def resolve_stock_names(user_query: str, max_results: int = 5) -> str:
    """把消息中的股票名称/缩写解析为 6 位代码（歧义时列出候选，不猜测）。

    Args:
        user_query: 含股票名称/缩写的文本。
        max_results: 最多返回的候选数。
    """
    try:
        items, lookup_ambiguous = _lookup_items(user_query, max_results)
    except Exception:  # noqa: BLE001
        return json.dumps({"error": "名称解析源暂不可用"}, ensure_ascii=False)
    names = [
        {"code": str(item.get("code", "")).strip(), "name": str(item.get("name", "")).strip()}
        for item in items
        if str(item.get("code", "")).strip() and str(item.get("name", "")).strip()
    ]
    match = name_match.match_names(user_query, names)
    ambiguous = list(dict.fromkeys([*lookup_ambiguous, *match.ambiguous_tokens]))
    return json.dumps(
        {
            "codes": list(match.codes),
            "candidates": [{"code": c.code, "name": c.name} for c in match.candidates],
            "ambiguous_tokens": ambiguous,
        },
        ensure_ascii=False,
    )


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
            _as_float(row.get("close")), _as_float(row.get("high")), _as_float(row.get("low")),
        )
        if c is None or h is None or low_value is None:
            continue
        close.append(c)
        high.append(h)
        low.append(low_value)
    if len(close) < _MIN_TECHNICAL_BARS:
        return None
    return high, low, close


def _gateway() -> Any:
    """取 QuantGateway（不可用时返回 None，回退在线内联计算）。"""
    try:
        from finance_agent.infrastructure.settings import get_postgres_connection_factory
        from finance_agent.infrastructure.persistence.postgres.async_run_repository import PostgresAsyncRunRepository
        from finance_agent.infrastructure.jobs.quant_gateway import CeleryQuantGateway

        return CeleryQuantGateway(
            async_repository=PostgresAsyncRunRepository(get_postgres_connection_factory())
        )
    except Exception:  # noqa: BLE001 - 网关不可用不阻断，回退内联
        return None


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


@tool
def compute_technical(
    config: RunnableConfig,
    stock_code: str,
    analysis_type: str = "both",
) -> str:
    """计算指定股票的技术指标（MA/MACD/KDJ/RSI/BOLL/WR）。

    Args:
        stock_code: 6 位股票代码。
        analysis_type: 取 fundamental 时跳过技术面计算。
    """
    sink = sink_of(config)
    if sink is None:
        return json.dumps({"error": "no_sink"}, ensure_ascii=False)
    if analysis_type == "fundamental":
        return json.dumps({"note": "用户只要基本面，跳过技术指标。"}, ensure_ascii=False)

    fetch = _stockdata.fetch_stock_data
    try:
        stock_data = fetch([stock_code])
    except Exception:  # noqa: BLE001
        sink.fail("stock_fetch_failed")
        return json.dumps({"error": "行情数据暂不可用"}, ensure_ascii=False)

    series = _technical_series(stock_data, stock_code)
    if series is None:
        sink.limit(f"insufficient_history:{stock_code}")
        return json.dumps(
            {"error": f"{stock_code} 历史数据不足，无法计算技术指标"}, ensure_ascii=False,
        )
    high, low, close = series

    gateway = _gateway()
    if gateway is not None:
        try:
            ref = gateway.submit(
                "technical_indicators",
                {"high": high, "low": low, "close": close},
                f"technical_indicators:{stock_code}",
                customer_id=str(sink.customer_id),
            )
            if not _wait_for_job(gateway, ref.job_id, 0.0):
                from finance_agent.shared.contracts import AsyncJobRef

                pending = list(sink.extras.get("pending_jobs") or [])
                pending.append(AsyncJobRef.model_validate(ref.model_dump()))
                sink.extras["pending_jobs"] = pending
                codes = dict(sink.extras.get("pending_job_codes") or {})
                codes[ref.job_id] = stock_code
                sink.extras["pending_job_codes"] = codes
                sink.limit("awaiting_quant")
                return json.dumps(
                    {"status": "processing", "job_id": ref.job_id,
                     "note": "技术指标计算已提交，稍后返回。"},
                    ensure_ascii=False,
                )
            result = gateway.result(ref.job_id) or {}
            indicators = result.get("indicators", {})
        except Exception:  # noqa: BLE001 - 网关异常回退内联计算
            logger.warning("quant_gateway_failed code=%s，回退内联", stock_code, exc_info=True)
            indicators = None
    else:
        indicators = None

    if indicators is None:
        from finance_agent.domains.research.technical import compute_all_indicators

        try:
            indicators = compute_all_indicators(high, low, close)
        except Exception:  # noqa: BLE001
            sink.fail("technical_compute_failed")
            return json.dumps({"error": "技术指标计算失败"}, ensure_ascii=False)

    technical = dict(sink.structured.get("technical_analysis") or {})
    technical[stock_code] = indicators
    sink.record("compute_technical", payload={"technical_analysis": technical})
    return json.dumps({"stock_code": stock_code, "indicators": indicators}, ensure_ascii=False, default=str)


_ANALYSIS_TYPES = ("fundamental", "technical", "both")


@tool
def evaluate_research(
    stock_codes: list[str],
    config: RunnableConfig,
    user_query: str = "",
    analysis_type: str = "both",
) -> str:
    """对给定标的做确定性研究评估，返回评分、行动结论、规则版本与证据 ID。

    这是领域内的确定性多跳：内部一次完成取数 → 质量门禁 → 风险优先裁决 →
    分标的结论，数字与结论均由规则计算，不由模型估算。涉及"能不能关注/该不该
    规避/评级/综合评分"这类结论性问题时应调用它，并原样引用返回的结论。

    Args:
        stock_codes: 6 位股票代码列表；多只时按各自独立结论给出（比较）。
        user_query: 可选的原始问题，用于保留请求上下文。
        analysis_type: 分析维度，取 fundamental/technical/both；风险维度始终纳入。
    """
    sink = sink_of(config)
    if sink is None:
        return json.dumps({"error": "no_sink"}, ensure_ascii=False)

    from finance_agent.domains.research.contracts import AnalysisKind, AnalysisRequest
    from finance_agent.domains.research.evaluation import evaluate, project_analysis_results
    from finance_agent.domains.research.expert.research_gateway import LiveStockDataGateway

    codes = [str(code).strip() for code in (stock_codes or []) if str(code).strip()]
    if not codes:
        return json.dumps({"error": "缺少股票代码"}, ensure_ascii=False)

    dimension = str(analysis_type or "").strip().lower()
    if dimension not in _ANALYSIS_TYPES:
        dimension = "both"

    profile = dict(sink.user_profile or {})
    request = AnalysisRequest(
        kind=AnalysisKind.COMPARISON if len(codes) >= 2 else AnalysisKind.SINGLE_STOCK,
        stock_codes=codes,
        analysis_type=dimension,
    )
    try:
        results, facts = evaluate(
            request,
            user_profile=profile,
            gateway=LiveStockDataGateway(),
        )
    except Exception:  # noqa: BLE001 - 评估失败诚实降级，不编造结论
        sink.fail("evaluate_research_failed")
        return json.dumps({"error": "研究评估暂不可用"}, ensure_ascii=False)

    projection = project_analysis_results(results)
    sink.record(
        "evaluate_research",
        payload={
            "analysis_results": projection["analysis_results"],
            "stock_analysis": projection["stock_analysis"],
            "research_request": request.model_dump(mode="json"),
            "facts": [fact.model_dump(mode="json") for fact in facts],
            "personalization_status": results[0].personalization_status if results else "",
        },
    )
    return json.dumps(
        {
            "conclusions": [
                {
                    "code": (result.request.stock_codes[0] if result.request else ""),
                    "rating": result.action.value,
                    "data_quality": result.data_quality,
                    "rule_version": result.rule_version,
                    "scores": result.scores,
                    "evidence_ids": list(result.evidence_ids),
                }
                for result in results
            ]
        },
        ensure_ascii=False,
        default=str,
    )


__all__ = [
    "STOCK_UNAVAILABLE",
    "compute_technical",
    "evaluate_research",
    "resolve_stock_names",
]
