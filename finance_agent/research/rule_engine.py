"""加载版本化规则并执行可重放的股票研究评估。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from finance_agent.research.contracts import (
    Action,
    AnalysisRequest,
    DataQuality,
    MarketDataSnapshot,
)


@dataclass(frozen=True)
class ScoreBreakdown:
    """确定性评估的分项评分。"""

    fundamental: float | None
    technical: float | None
    risk: float | None
    suitability: float | None
    total: float | None
    fundamental_technical_conflict: bool


@dataclass(frozen=True)
class DeterministicAssessment:
    """规则引擎输出，供流水线和审计层复用。"""

    rule_version: str
    action: Action
    scores: ScoreBreakdown
    personalization_status: str
    restrictions: tuple[str, ...]


# 版本标识 → 仓库内已审定的规则文件；重放按审计记录里的版本号精确加载。
_RULE_FILES = {"research_rules/v1": "v1.json"}


def load_rules(version: str = "research_rules/v1") -> dict[str, Any]:
    """按版本标识加载仓库内规则集；未知版本必须显式失败，不得静默回退。"""
    key = str(version or "").strip()
    filename = _RULE_FILES.get(key)
    if filename is None:
        raise ValueError(f"未知规则版本：{version}")
    path = Path(__file__).with_name("rules") / filename
    rules = json.loads(path.read_text(encoding="utf-8"))
    if str(rules.get("version", "")) != key:
        raise ValueError(f"规则文件与版本标识不一致：{path} 声明为 {rules.get('version')}")
    return rules


def _bounded_score(value: Any) -> float | None:
    """将外部计算值限制到 0–100，无法转换则表示缺失。"""
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return None


class RuleEngine:
    """完全由快照和版本化配置决定的规则评估器。"""

    def __init__(self, rules: dict[str, Any]):
        self._rules = rules

    @property
    def version(self) -> str:
        """返回当前已加载规则集的稳定版本标识。"""
        return str(self._rules["version"])

    @classmethod
    def default(cls) -> "RuleEngine":
        """加载仓库内审定的首版规则。"""
        return cls(load_rules())

    def evaluate(
        self,
        snapshot: MarketDataSnapshot,
        request: AnalysisRequest,
    ) -> DeterministicAssessment:
        """根据数据质量、风险和分项分数执行风险优先裁决。"""
        quality = snapshot.quality
        restrictions = list(quality.missing_critical) + list(quality.warnings)
        if quality.is_critical:
            scores = ScoreBreakdown(None, None, None, None, None, False)
            return DeterministicAssessment(
                rule_version=self._rules["version"],
                action=Action.INSUFFICIENT_DATA,
                scores=scores,
                personalization_status=self._personalization_status(request),
                restrictions=tuple(restrictions),
            )

        minimum_history_bars = int(self._rules["hard_gates"]["minimum_history_bars"])
        insufficient_history = [
            security.code
            for security in snapshot.securities
            if len(security.history.get("data", [])) < minimum_history_bars
        ]
        if insufficient_history:
            restrictions.append("minimum_history_bars")
            scores = ScoreBreakdown(None, None, None, None, None, False)
            return DeterministicAssessment(
                rule_version=self._rules["version"],
                action=Action.INSUFFICIENT_DATA,
                scores=scores,
                personalization_status=self._personalization_status(request),
                restrictions=tuple(dict.fromkeys(restrictions)),
            )

        primary = snapshot.securities[0] if snapshot.securities else None
        indicators = primary.indicators if primary is not None else {}
        score_restrictions = indicators.get("score_restrictions", [])
        if isinstance(score_restrictions, list):
            restrictions.extend(
                item for item in score_restrictions
                if isinstance(item, str) and item
            )
        fundamental = _bounded_score(indicators.get("fundamental_score"))
        technical = _bounded_score(indicators.get("technical_score"))
        risk = _bounded_score(indicators.get("risk_score"))
        suitability = self._suitability_score(request, indicators)
        conflict = self._has_fundamental_technical_conflict(fundamental, technical)
        total = self._weighted_total(fundamental, technical, risk, suitability)
        scores = ScoreBreakdown(
            fundamental=fundamental,
            technical=technical,
            risk=risk,
            suitability=suitability,
            total=total,
            fundamental_technical_conflict=conflict,
        )
        action = self._decide_action(quality, risk, scores)
        return DeterministicAssessment(
            rule_version=self._rules["version"],
            action=action,
            scores=scores,
            personalization_status=self._personalization_status(request),
            restrictions=tuple(restrictions),
        )

    def _suitability_score(
        self,
        request: AnalysisRequest,
        indicators: dict[str, Any],
    ) -> float | None:
        if not request.profile_complete:
            return None
        return _bounded_score(indicators.get("suitability_score", 50.0))

    @staticmethod
    def _personalization_status(request: AnalysisRequest) -> str:
        return "personalized" if request.profile_complete else "research_candidate"

    def _has_fundamental_technical_conflict(
        self,
        fundamental: float | None,
        technical: float | None,
    ) -> bool:
        if fundamental is None or technical is None:
            return False
        spread = self._rules["actions"]["conflict_spread"]
        return abs(fundamental - technical) >= spread

    def _weighted_total(
        self,
        fundamental: float | None,
        technical: float | None,
        risk: float | None,
        suitability: float | None,
    ) -> float | None:
        required = {"fundamental": fundamental, "technical": technical, "risk": risk}
        if any(score is None for score in required.values()):
            return None
        weights = self._rules["weights"]
        weighted = sum(required[name] * weights[name] for name in required)
        used_weight = sum(weights[name] for name in required)
        if suitability is not None:
            weighted += suitability * weights["suitability"]
            used_weight += weights["suitability"]
        return round(weighted / used_weight, 2)

    def _decide_action(
        self,
        quality: DataQuality,
        risk: float | None,
        scores: ScoreBreakdown,
    ) -> Action:
        if quality.is_critical:
            return Action.INSUFFICIENT_DATA
        if risk is None:
            return Action.INSUFFICIENT_DATA
        if risk <= self._rules["actions"]["avoid_maximum_score"]:
            return Action.AVOID
        if scores.fundamental_technical_conflict:
            return Action.WAIT
        if scores.total is None:
            return Action.INSUFFICIENT_DATA
        if scores.total >= self._rules["actions"]["watch_minimum_score"]:
            return Action.WATCH
        if scores.total <= self._rules["actions"]["avoid_maximum_score"]:
            return Action.AVOID
        return Action.WAIT
