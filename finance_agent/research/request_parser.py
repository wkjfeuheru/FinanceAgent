"""将编排状态确定性解析为研究请求，不调用模型或数据源。"""

from __future__ import annotations

import re
from typing import Any

from finance_agent.research.contracts import AnalysisKind, AnalysisRequest
from finance_agent.research.theme_registry import ThemeRegistry, default_theme_registry


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
    for key in ("stock_analysis", "stock_recommendation"):
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


class UnknownThemeError(ValueError):
    """主题文本未被注册表识别；上层可用该文本做候选搜索，而非直接失败。"""

    def __init__(self, theme_text: str) -> None:
        self.theme_text = theme_text.strip()
        super().__init__(f"无法识别主题：{self.theme_text}，请提供有效的主题名称或 theme_id")


def _theme_texts(slots: dict[str, Any]) -> list[str]:
    """收集槽位中所有可能的主题文本（显式 theme_id / theme / 自由文本 themes）。"""
    raw_values = [slots.get("theme_id"), slots.get("theme")]
    themes = slots.get("themes")
    if isinstance(themes, (list, tuple)):
        raw_values.extend(themes)
    elif themes:
        raw_values.append(themes)
    texts: list[str] = []
    for raw in raw_values:
        if isinstance(raw, dict):
            raw = raw.get("id") or raw.get("name")
        value = str(raw).strip() if raw is not None else ""
        if value and value not in texts:
            texts.append(value)
    return texts


def _resolve_theme_id(
    message: str,
    slots: dict[str, Any],
    *,
    has_codes: bool,
    registry: ThemeRegistry | None = None,
) -> str | None:
    """把槽位或消息中的主题文本解析为已注册的 ``theme_id``。

    解析顺序：槽位主题文本 → 消息中的注册主题名。未被注册表识别时，
    无股票代码则抛 ``UnknownThemeError``（由上层尝试候选搜索），有代码则忽略主题文本。
    """
    registry = registry or default_theme_registry()
    message = message or ""

    for text in _theme_texts(slots):
        resolved = registry.resolve(text)
        if resolved:
            return resolved

    lowered = message.lower()
    for entry in registry.list_themes():
        for name in sorted(entry.names(), key=len, reverse=True):
            if name and name.lower() in lowered:
                return entry.theme_id

    if _theme_texts(slots) and not has_codes:
        raise UnknownThemeError(_theme_texts(slots)[0])
    if "主题" in message and not has_codes:
        raise UnknownThemeError(message.strip() or "未知主题")
    return None


def parse_analysis_request(
    message: str,
    *,
    resolved_stocks: list[dict[str, Any]] | None,
    intent_slots: dict[str, Any] | None,
    user_profile: dict[str, Any] | None,
    theme_registry: ThemeRegistry | None = None,
) -> AnalysisRequest:
    """从槽位、股票解析结果和消息构建确定性研究请求。

    股票优先级固定为：显式槽位、已解析股票、消息中的六位代码。
    """
    slots = _market_slots(intent_slots or {})
    slot_codes = _ordered_codes(slots.get("stock_codes", slots.get("codes", [])))
    resolved_codes = _ordered_codes(resolved_stocks or [])
    message_codes = _ordered_codes(_CODE_PATTERN.findall(message or ""))
    codes = slot_codes or resolved_codes or message_codes
    theme_id = _resolve_theme_id(
        message, slots, has_codes=bool(codes), registry=theme_registry,
    )

    comparison_requested = (
        any(word.lower() in (message or "").lower() for word in _COMPARISON_WORDS)
        and len(codes) >= 2
    )
    kind = (
        AnalysisKind.THEME_SCREENING if theme_id
        else AnalysisKind.COMPARISON if comparison_requested
        else AnalysisKind.SINGLE_STOCK
    )

    profile = user_profile or {}
    profile_complete = bool(
        str(profile.get("risk_preference", "")).strip()
        and str(profile.get("holding_period", "")).strip()
    )
    return AnalysisRequest(
        kind=kind,
        stock_codes=codes,
        theme_id=theme_id,
        indicators=_normalize_indicators(slots.get("indicators", [])),
        profile_complete=profile_complete,
    )
