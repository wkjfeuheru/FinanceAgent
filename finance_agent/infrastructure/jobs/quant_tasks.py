"""量化计算任务：技术指标计算。

纯函数 ``run_quant_task`` 承载全部计算逻辑，Celery 任务只是它的 JSON 包装；
任务不 import LangGraph，也不写 checkpoint。
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Callable

from finance_agent.infrastructure.jobs.celery_app import celery_app


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
    from finance_agent.domains.research.technical import compute_all_indicators

    high = list(payload.get("high") or [])
    low = list(payload.get("low") or [])
    close = list(payload.get("close") or [])
    if not close or not (len(high) == len(low) == len(close)):
        raise QuantTaskError("high/low/close must be non-empty and equal length")
    return {"indicators": _jsonable(compute_all_indicators(high, low, close))}


_TASKS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "technical_indicators": _technical_indicators,
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
