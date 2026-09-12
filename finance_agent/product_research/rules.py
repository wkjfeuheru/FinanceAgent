"""产品风险与用户画像适配规则。"""

from __future__ import annotations

import re
from typing import Any


_RISK_ALIASES = {
    "r1": "R1", "低": "R1", "低风险": "R1", "谨慎": "R1",
    "r2": "R2", "中低": "R2", "中低风险": "R2", "较低": "R2", "稳健": "R2",
    "r3": "R3", "中": "R3", "中风险": "R3",
    "r4": "R4", "中高": "R4", "中高风险": "R4", "较高": "R4",
    "r5": "R5", "高": "R5", "高风险": "R5", "激进": "R5",
}
_USER_RISK_ALIASES = {
    "保守": "R1", "谨慎": "R1", "低": "R1", "低风险": "R1",
    "稳健": "R2", "中低": "R2", "中低风险": "R2",
    "平衡": "R3", "中性": "R3", "中": "R3", "中风险": "R3",
    "积极": "R4", "中高": "R4", "中高风险": "R4",
    "进取": "R5", "激进": "R5", "高": "R5", "高风险": "R5",
}


def normalize_risk(value: Any) -> str | None:
    raw = str(value or "").strip().lower().replace(" ", "")
    if not raw:
        return None
    explicit_level = re.match(r"^r([1-5])(?:\D.*)?$", raw)
    if explicit_level:
        return f"R{explicit_level.group(1)}"
    return _RISK_ALIASES.get(raw) or _RISK_ALIASES.get(str(value or "").strip())


def normalize_profile_risk(value: Any) -> str | None:
    raw = str(value or "").strip().lower().replace(" ", "")
    explicit_level = re.match(r"^r([1-5])(?:\D.*)?$", raw)
    if explicit_level:
        return f"R{explicit_level.group(1)}"
    return _USER_RISK_ALIASES.get(str(value or "").strip())


def normalize_horizon(value: Any) -> str | None:
    """把持有期限归一为 short/medium/long；无法识别返回 None。

    除固定说法外，也按数量级判定：≥1 年 → long，≥6 个月 → medium，
    其余月/周/天 → short。避免"3年""18个月"这类常见表述被当作未识别。
    """
    raw = str(value or "").strip().lower().replace(" ", "")
    aliases = {
        "short": "short", "短期": "short", "3个月": "short", "三个月": "short",
        "medium": "medium", "中期": "medium", "6个月": "medium", "半年": "medium",
        "long": "long", "长期": "long", "1年": "long", "12个月": "long", "一年": "long",
    }
    if raw in aliases:
        return aliases[raw]
    years = re.fullmatch(r"(\d+)年", raw)
    if years:
        return "long" if int(years.group(1)) >= 1 else None
    months = re.fullmatch(r"(\d+)个月", raw)
    if months:
        count = int(months.group(1))
        if count >= 12:
            return "long"
        return "medium" if count >= 6 else "short"
    if re.fullmatch(r"\d+(?:周|天)", raw):
        return "short"
    return None


def evaluate_suitability(
    *,
    risk_level: str | None,
    recommended_holding_period: Any,
    profile: dict[str, Any],
) -> tuple[str, list[str]]:
    """按用户风险上限和产品建议期限给出适配状态。"""
    user_risk = normalize_profile_risk(profile.get("risk_preference"))
    user_horizon = normalize_horizon(profile.get("holding_period"))
    if not user_risk or not user_horizon:
        return "not_evaluated", ["风险偏好和持有期限必须同时提供"]
    if not risk_level:
        return "unavailable", ["产品库未提供可识别的风险等级"]
    product_horizon = normalize_horizon(recommended_holding_period)
    if not product_horizon:
        return "unavailable", ["产品库未提供可识别的建议持有期限"]

    reasons: list[str] = []
    if int(risk_level[1]) <= int(user_risk[1]):
        reasons.append(f"产品风险 {risk_level} 不高于用户风险承受范围 {user_risk}")
    else:
        reasons.append(f"产品风险 {risk_level} 高于用户风险承受范围 {user_risk}")
    if product_horizon == user_horizon:
        reasons.append(f"建议持有期限与用户期限均为 {user_horizon}")
    else:
        reasons.append(f"建议持有期限 {product_horizon} 与用户期限 {user_horizon} 不一致")
    matched = int(risk_level[1]) <= int(user_risk[1]) and product_horizon == user_horizon
    return ("matched" if matched else "unmatched"), reasons
