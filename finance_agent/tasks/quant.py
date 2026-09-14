"""量化计算任务：技术指标、批量评分、回测与重放。

纯函数 ``run_quant_task`` 承载全部计算逻辑，Celery 任务只是它的 JSON 包装；
任务不 import LangGraph，也不写 checkpoint。
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Callable

from finance_agent.celery_app import celery_app


class QuantTaskError(ValueError):
    """任务输入不合法或不支持。"""


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _technical_indicators(payload: dict[str, Any]) -> dict[str, Any]:
    from finance_agent.orchestrator.tools.technical import compute_all_indicators

    high = list(payload.get("high") or [])
    low = list(payload.get("low") or [])
    close = list(payload.get("close") or [])
    if not close or not (len(high) == len(low) == len(close)):
        raise QuantTaskError("high/low/close must be non-empty and equal length")
    return {"indicators": _jsonable(compute_all_indicators(high, low, close))}


def _batch_score(payload: dict[str, Any]) -> dict[str, Any]:
    from finance_agent.research.contracts import AnalysisRequest, MarketDataSnapshot
    from finance_agent.research.rule_engine import RuleEngine

    snapshot = MarketDataSnapshot.model_validate(payload["snapshot"])
    requests = [AnalysisRequest.model_validate(item) for item in payload.get("requests") or []]
    if not requests:
        raise QuantTaskError("requests must contain at least one AnalysisRequest")
    engine = RuleEngine.default()
    return {
        "assessments": [
            _jsonable(engine.evaluate(snapshot, request)) for request in requests
        ]
    }


def _walk_forward_backtest(payload: dict[str, Any]) -> dict[str, Any]:
    from finance_agent.research.backtest import (
        FeatureSnapshot,
        InMemoryFeatureSnapshotRepository,
        run_walk_forward_backtest,
    )

    snapshots = [
        FeatureSnapshot(
            theme_id=item["theme_id"],
            stock_code=item["stock_code"],
            industry=item.get("industry", ""),
            rule_version=item["rule_version"],
            as_of=datetime.fromisoformat(item["as_of"]),
            payload=dict(item.get("payload") or {}),
        )
        for item in payload.get("snapshots") or []
    ]
    report = run_walk_forward_backtest(
        InMemoryFeatureSnapshotRepository(snapshots),
        payload["theme_id"],
        date.fromisoformat(payload["start"]),
        date.fromisoformat(payload["end"]),
        payload["rule_version"],
        rebalance_dates=[
            date.fromisoformat(value) for value in payload.get("rebalance_dates") or []
        ]
        or None,
    )
    return {"report": _jsonable(report)}


def _research_replay(payload: dict[str, Any]) -> dict[str, Any]:
    from finance_agent.research.replay import replay_research_run

    outcome = replay_research_run(
        research_run_id=payload["research_run_id"],
        request_data=payload.get("request_data"),
        results=list(payload.get("results") or []),
        snapshot_manifest=list(payload.get("snapshot_manifest") or []),
        rule_version=payload.get("rule_version", ""),
    )
    return {"outcome": _jsonable(outcome)}


_TASKS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "technical_indicators": _technical_indicators,
    "batch_score": _batch_score,
    "theme_screening": _batch_score,
    "walk_forward_backtest": _walk_forward_backtest,
    "research_replay": _research_replay,
}


def supported_kinds() -> list[str]:
    return sorted(_TASKS)


def run_quant_task(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """执行一次量化计算；未知任务或不合法输入显式失败，不返回伪结果。"""
    handler = _TASKS.get(kind)
    if handler is None:
        raise QuantTaskError(f"unsupported quant task: {kind}")
    return handler(dict(payload or {}))


@celery_app.task(name="finance.quant.run", bind=True)
def run_quant_task_celery(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:  # noqa: ANN001
    """Celery 包装：只做纯计算并返回 JSON 安全产物。"""
    return {"kind": kind, "result": run_quant_task(kind, payload)}
