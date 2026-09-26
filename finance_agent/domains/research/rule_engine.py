"""加载版本化规则并执行可重放的股票研究评估。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from finance_agent.domains.research.contracts import (
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
#
# **新增版本而不是替换**是硬要求：审计与快照重放按记录里的版本号精确加载，
# 旧记录必须一直可重放。v1.1 的规则**内容与 v1 完全相同**，但它标记的是不同的
# 评分口径——数据源补上 PE/PB 之后，基本面分数由 5 项而不是 3 项平均而成，
# 同样的输入会得到不同的分数。若沿用 v1，`(stock_code, rule_version,
# as_of)` 上的 ON CONFLICT DO UPDATE 会在同一个键上覆盖掉旧口径的历史快照。
_RULE_FILES = {
    "research_rules/v1": "v1.json",
    "research_rules/v1.1": "v1.1.json",
    "research_rules/v1.2": "v1.2.json",
}

# 当前默认版本。这里是唯一真源——此前默认值重复声明在 load_rules 的参数、
# refresh 的服务默认值与 snapshot_builder 的常量三处，容易各自漂移。
#
# v1.2 口径变化：适配度（suitability）在缺值时不再默认 50.0。此前画像完整的请求
# 会被静默注入一个中性适配度并计入加权总分，等于**凭空造分**、可能改变关注/观望
# 结论；现在缺值即排除该项，只按实际可计算的三项加权。口径变化必须换版本号，
# 否则同一 `(stock_code, rule_version, as_of)` 键上的 upsert 会覆盖旧口径快照。
CURRENT_RULES_VERSION = "research_rules/v1.2"


def load_rules(version: str = CURRENT_RULES_VERSION) -> dict[str, Any]:
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


def _selected_dimensions(request: AnalysisRequest) -> frozenset[str]:
    """返回参与加权的维度集合。

    ``analysis_type`` 决定基本面/技术面是否参与；**风险维度任何模式下都强制
    纳入**（安全门禁），因此 ``both`` 之外的取值是"收窄"而非"排除风险"。
    """
    analysis_type = getattr(request, "analysis_type", "both") or "both"
    if analysis_type == "fundamental":
        return frozenset({"fundamental", "risk"})
    if analysis_type == "technical":
        return frozenset({"technical", "risk"})
    return frozenset({"fundamental", "technical", "risk"})


def _visible_restrictions(codes: Any, selected: frozenset[str]) -> list[str]:
    """过滤掉"被用户排除的维度"所产生的评分级缺失码。

    只丢弃评分层的 ``fundamental*`` / ``technical*`` 前缀码；质量门禁的
    warnings（数据完整性披露）不在 ``score_restrictions`` 里，不受影响。
    """
    dropped_prefix = {
        "fundamental": "fundamental",
        "technical": "technical",
    }
    hidden = [
        prefix for dimension, prefix in dropped_prefix.items() if dimension not in selected
    ]
    return [
        code for code in codes
        if not any(code.startswith(prefix) for prefix in hidden)
    ]


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
        selected = _selected_dimensions(request)
        score_restrictions = indicators.get("score_restrictions", [])
        if isinstance(score_restrictions, list):
            restrictions.extend(
                _visible_restrictions(
                    (item for item in score_restrictions if isinstance(item, str) and item),
                    selected,
                )
            )
        fundamental = (
            _bounded_score(indicators.get("fundamental_score"))
            if "fundamental" in selected else None
        )
        technical = (
            _bounded_score(indicators.get("technical_score"))
            if "technical" in selected else None
        )
        risk = _bounded_score(indicators.get("risk_score"))
        suitability = self._suitability_score(request, indicators)
        conflict = self._has_fundamental_technical_conflict(fundamental, technical)
        total = self._weighted_total(fundamental, technical, risk, suitability, selected)
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
        """适配度：仅在画像完整且**确有**适配度指标时才计分。

        曾经在缺值时默认 50.0——那是凭空造出的中性分并会进入加权总分，
        可改变关注/观望结论。现在缺值即返回 None，由 ``_weighted_total``
        排除该项，只按实际可计算的项加权。
        """
        if not request.profile_complete:
            return None
        return _bounded_score(indicators.get("suitability_score"))

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
        selected: frozenset[str],
    ) -> float | None:
        """按选定维度加权求总分。

        只有**选定维度**（外加始终纳入的风险）进入 required 集合：被用户排除的
        维度（值为 None）不参与也不阻断；但**选定却缺失**的维度仍返回 None，
        保持"数据缺失不得静默降级"的护栏。
        """
        candidates = {"fundamental": fundamental, "technical": technical, "risk": risk}
        required = {name: value for name, value in candidates.items() if name in selected}
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
