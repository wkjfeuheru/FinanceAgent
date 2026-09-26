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


__all__ = ["normalize_profile_risk", "normalize_risk"]
