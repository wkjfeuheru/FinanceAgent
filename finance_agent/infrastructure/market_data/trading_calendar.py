"""交易日历：按 Provider 日历统计交易日间隔，取数失败时回退工作日估算。

新鲜度门禁必须用交易日而不是自然日，否则长假后的第一个交易日会把仍然
有效的行情误判为陈旧；反过来，Provider 日历不可用时也必须给出可解释的
降级依据，而不是静默当成交易日。

返回值第二项是计数依据，会写入证据 provenance：

- ``provider``：Provider 交易日历；
- ``weekday_fallback``：已配置日历但取数失败，按工作日估算（会额外告警）。
"""

from __future__ import annotations

import logging
import threading
from datetime import date
from typing import Any

from finance_agent.infrastructure.market_data.normalization import normalize_trade_cal_records
from finance_agent.domains.research.quality_gates import market_date, weekday_trading_days

logger = logging.getLogger(__name__)

_LIST_KEYS = ("data", "items", "results", "list", "records")
_MAX_CACHE_ENTRIES = 256
_cache: dict[tuple[str, str], tuple[int, str]] = {}
_cache_lock = threading.Lock()


def _rows(payload: Any) -> list[dict[str, Any]]:
    """提取交易日历记录列表，兼容常见的列表包装。"""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in _LIST_KEYS:
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]
    return []


def _is_open(value: Any) -> bool:
    """判断交易日标记；缺失视为交易日，避免把有效日期漏算。"""
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text not in {"0", "false", "no", "off", "否", "休市", "非交易日"}


def _count_from_rows(rows: list[dict[str, Any]], start: date, end: date) -> int | None:
    """统计 start 之后（不含）到 end（含）之间的交易日数量。"""
    days = []
    for row in rows:
        moment = market_date(row.get("cal_date"))
        if moment is None or not _is_open(row.get("is_open")):
            continue
        days.append(moment)
    if not days:
        return None
    return sum(1 for day in days if start < day <= end)


def _manager_factory() -> Any:
    """返回 ProviderManager；独立成函数便于测试注入，也避免模块级网络依赖。"""
    from finance_agent.infrastructure.market_data.provider_manager import get_provider_manager

    return get_provider_manager()


def _query_provider(start: date, end: date) -> tuple[int, str]:
    """向 Provider 查询交易日历；任何失败都降级为工作日估算。"""
    try:
        payload = _manager_factory().get_trade_cal(start.isoformat(), end.isoformat())
        count = _count_from_rows(_rows(normalize_trade_cal_records(payload)), start, end)
        if count is None:
            raise ValueError("交易日历记录缺少可用日期字段")
        return count, "provider"
    except Exception as exc:  # Provider 或数据源能力不足：降级但必须可解释
        logger.info("交易日历不可用，回退工作日计数: %s", exc)
        count, _ = weekday_trading_days(start, end)
        return count, "weekday_fallback"


def trading_days_between(start: date, end: date) -> tuple[int, str]:
    """返回 (start 之后至 end 的交易日数, 计数依据)。

    结果按 (start, end) 进程内缓存（含失败结果），避免多只标的研究任务逐只
    重复请求日历；缓存满时整体清空，保证内存有界。
    """
    if end <= start:
        return 0, "provider"
    key = (start.isoformat(), end.isoformat())
    with _cache_lock:
        cached = _cache.get(key)
    if cached is not None:
        return cached
    result = _query_provider(start, end)
    with _cache_lock:
        if len(_cache) >= _MAX_CACHE_ENTRIES:
            _cache.clear()
        _cache[key] = result
    return result


def clear_cache() -> None:
    """清空日历缓存，供测试隔离使用。"""
    with _cache_lock:
        _cache.clear()


__all__ = ["clear_cache", "trading_days_between"]
