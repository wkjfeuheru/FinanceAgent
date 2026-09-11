"""将编排状态确定性解析为研究请求，不调用模型或数据源。"""

from __future__ import annotations

import re
from typing import Any

from finance_agent.research.contracts import AnalysisKind, AnalysisRequest


_CODE_PATTERN = re.compile(r"(?<!\d)(?:60\d{4}|00\d{4}|30\d{4}|68\d{4}|8\d{5}|4\d{5})(?!\d)")
_COMPARISON_WORDS = ("比较", "对比", "相比", "哪个好", "孰优", "vs", "VS")
_INDICATOR_ALIASES = {
    "macd": "MACD",
    "kdj": "KDJ",
    "rsi": "RSI",
    "boll": "BOLL",
    "布林": "BOLL",
    "ma": "MA",
    "m.a.": "MA",
    "均线": "MA",
    "wr": "WR",
    "威廉": "WR",
}


def _ordered_codes(raw_codes: Any) -> list[str]:
    """按输入顺序提取并去重非空股票代码。"""
    if not isinstance(raw_codes, list):
        return []
    seen: set[str] = set()
    result: list[str] = []
    for raw_code in raw_codes:
        if isinstance(raw_code, dict):
            raw_code = raw_code.get("code", "")
        code = str(raw_code).strip()
        if code and code not in seen:
            seen.add(code)
            result.append(code)
    return result


def _market_slots(intent_slots: dict[str, Any]) -> dict[str, Any]:
    """兼容按意图存储或直接传入的槽位字典。"""
    if not isinstance(intent_slots, dict):
        return {}
    for key in ("market_query", "stock_recommendation", "stock_analysis"):
        candidate = intent_slots.get(key)
        if isinstance(candidate, dict):
            return candidate
    return intent_slots


def _normalize_indicators(raw_indicators: Any) -> list[str]:
    """将工具层接受的指标别名标准化为大写名称。"""
    values = raw_indicators if isinstance(raw_indicators, list) else []
    normalized: list[str] = []
    for raw_value in values:
        value = str(raw_value).strip()
        if not value:
            continue
        standard = _INDICATOR_ALIASES.get(value.lower(), value.upper())
        if standard not in set(_INDICATOR_ALIASES.values()):
            standard = None
        if standard and standard not in normalized:
            normalized.append(standard)
    return normalized


def parse_analysis_request(
    message: str,
    *,
    resolved_stocks: list[dict[str, Any]] | None,
    intent_slots: dict[str, Any] | None,
    user_profile: dict[str, Any] | None,
) -> AnalysisRequest:
    """从槽位、股票解析结果和消息构建确定性研究请求。

    股票优先级固定为：显式槽位、已解析股票、消息中的六位代码。
    """
    slots = _market_slots(intent_slots or {})
    slot_codes = _ordered_codes(slots.get("stock_codes", slots.get("codes", [])))
    resolved_codes = _ordered_codes(resolved_stocks or [])
    message_codes = _ordered_codes(_CODE_PATTERN.findall(message or ""))
    codes = slot_codes or resolved_codes or message_codes

    comparison_requested = (
        any(word.lower() in (message or "").lower() for word in _COMPARISON_WORDS)
        and len(codes) >= 2
    )
    kind = AnalysisKind.COMPARISON if comparison_requested else AnalysisKind.SINGLE_STOCK

    profile = user_profile or {}
    profile_complete = bool(
        str(profile.get("risk_preference", "")).strip()
        and str(profile.get("holding_period", "")).strip()
    )
    return AnalysisRequest(
        kind=kind,
        stock_codes=codes,
        indicators=_normalize_indicators(slots.get("indicators", [])),
        profile_complete=profile_complete,
    )
