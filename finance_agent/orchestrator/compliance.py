"""统一合规出口（设计 §6.8、§12）。

所有可见输出（成功、部分、降级、恢复后）都必须经过本子图：

    draft -> deterministic_policy_check -> semantic_policy_check
          -> pass -> final
          -> rewrite once -> recheck -> pass
                                   -> block

改写不得改变事实、数值和引用，只能删除违规表达、调整措辞或补充风险提示。
复检仍失败时 fail-closed。审计保存原因码、规则版本、草稿哈希与最终动作，
不向前端暴露内部违规草稿。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field

from finance_agent.contracts.schema.enums import RunStatus
from finance_agent.middleware.content_filter import check_sensitive_words

RULE_VERSION = "compliance/v1"
RISK_DISCLAIMER = "以上内容仅供参考，不构成投资建议；市场有风险，投资需谨慎。"
BLOCKED_RESPONSE = "抱歉，本次回复未能通过合规校验，已为您拦截。请换一种方式提问。"

_NUMBER = re.compile(r"\d+(?:\.\d+)?")


class EvidenceRef(BaseModel):
    """一条被引用的证据事实；改写前后必须逐条保持。"""

    fact_id: str
    value: Any = None


class ComplianceResult(BaseModel):
    """合规子图终态。"""

    # audited：内容来自受信来源（如运维审核过的 FAQ 原文），只做检查与审计记录，
    # 不改写也不拦截——风险词汇在“解释规则”的语境里是合法且必要的表述。
    action: Literal["passed", "rewritten", "blocked", "audited"]
    response: str
    reason_codes: list[str] = Field(default_factory=list)
    rewrite_count: int = 0
    rule_version: str = RULE_VERSION
    draft_hash: str = ""
    evidence: list[EvidenceRef] = Field(default_factory=list)
    audit: dict[str, Any] = Field(default_factory=dict)


@dataclass
class CompliancePolicy:
    """确定性规则 + 可选语义校验 + 一次受约束改写的策略集合。"""

    version: str = RULE_VERSION
    check: Callable[[str], list[str]] = field(default_factory=lambda: _default_check)
    semantic_check: Callable[[str], list[str]] | None = None
    rewrite: Callable[[str], str | None] | None = None


def _default_check(text: str) -> list[str]:
    return [f"sensitive_word:{word}" for word in check_sensitive_words(text or "")]


def _default_rewrite(text: str) -> str:
    """删除命中的违规表达，其余（含数值与结构）保持不变。"""
    rewritten = text or ""
    for word in check_sensitive_words(rewritten):
        rewritten = rewritten.replace(word, "")
    rewritten = re.sub(r"[ \t]{2,}", " ", rewritten).strip()
    if rewritten and RISK_DISCLAIMER not in rewritten:
        rewritten = f"{rewritten}\n\n{RISK_DISCLAIMER}"
    return rewritten


def default_policy() -> CompliancePolicy:
    return CompliancePolicy(
        version=RULE_VERSION,
        check=_default_check,
        semantic_check=None,
        rewrite=_default_rewrite,
    )


def always_reject_policy() -> CompliancePolicy:
    """语义校验与改写都失败的策略；用于验证复检拦截。"""

    return CompliancePolicy(
        version="compliance/reject",
        check=lambda text: ["semantic_violation"],
        semantic_check=None,
        rewrite=None,
    )


def _draft_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _numbers(text: str) -> set[str]:
    return set(_NUMBER.findall(text or ""))


def _preserves_facts(draft: str, rewritten: str) -> bool:
    """改写不得丢失原有数值。"""
    return _numbers(draft) <= _numbers(rewritten)


def run_compliance(
    *,
    draft: str,
    evidence: list[EvidenceRef] | list[dict[str, Any]] | None = None,
    policy: CompliancePolicy | None = None,
    model: Any = None,
    audit_only: bool = False,
    rewrite_budget: int | None = None,
) -> ComplianceResult:
    """执行确定性规则、可选语义校验、一次改写与复检。

    ``audit_only=True`` 用于内容来自受信来源（运维审核过的 FAQ 原文）的场景：
    仍然执行检查并把命中项写入审计，但**不改写、不拦截**。因为风险词汇在
    “解释投资规则”的语境里是合法且必需的（例如 FAQ 条目名就是
    “什么是操纵市场？”），删词会把答案改成病句。

    ``rewrite_budget`` 来自 ``RunBudgets.compliance_rewrites``（None 时取
    config 默认）。为 0 时不尝试改写、直接 fail-closed——预算收紧到零时
    宁可拦截也不放行未校验内容。
    """
    if rewrite_budget is None:
        from finance_agent import config

        rewrite_budget = config.ORCHESTRATION_COMPLIANCE_REWRITES

    active = policy or default_policy()
    refs = [item if isinstance(item, EvidenceRef) else EvidenceRef.model_validate(item) for item in (evidence or [])]
    draft_hash = _draft_hash(draft)

    reasons = list(active.check(draft))
    if active.semantic_check is not None:
        reasons += list(active.semantic_check(draft))

    if audit_only:
        action = "audited" if reasons else "passed"
        return ComplianceResult(
            action=action,
            response=draft,
            reason_codes=reasons,
            rewrite_count=0,
            rule_version=active.version,
            draft_hash=draft_hash,
            evidence=refs,
            audit=_audit(action, reasons, 0, active.version, draft_hash),
        )

    if not reasons:
        return ComplianceResult(
            action="passed",
            response=draft,
            reason_codes=[],
            rewrite_count=0,
            rule_version=active.version,
            draft_hash=draft_hash,
            evidence=refs,
            audit=_audit("passed", [], 0, active.version, draft_hash),
        )

    if active.rewrite is None or rewrite_budget < 1:
        return ComplianceResult(
            action="blocked",
            response=BLOCKED_RESPONSE,
            reason_codes=reasons,
            rewrite_count=0,
            rule_version=active.version,
            draft_hash=draft_hash,
            evidence=refs,
            audit=_audit("blocked", reasons, 0, active.version, draft_hash),
        )

    rewritten = active.rewrite(draft)
    if rewritten is None or not _preserves_facts(draft, rewritten):
        return ComplianceResult(
            action="blocked",
            response=BLOCKED_RESPONSE,
            reason_codes=reasons + ["rewrite_changed_facts"],
            rewrite_count=1,
            rule_version=active.version,
            draft_hash=draft_hash,
            evidence=refs,
            audit=_audit("blocked", reasons, 1, active.version, draft_hash),
        )

    recheck = list(active.check(rewritten))
    if active.semantic_check is not None:
        recheck += list(active.semantic_check(rewritten))
    if recheck:
        return ComplianceResult(
            action="blocked",
            response=BLOCKED_RESPONSE,
            reason_codes=recheck,
            rewrite_count=1,
            rule_version=active.version,
            draft_hash=draft_hash,
            evidence=refs,
            audit=_audit("blocked", recheck, 1, active.version, draft_hash),
        )

    return ComplianceResult(
        action="rewritten",
        response=rewritten,
        reason_codes=reasons,
        rewrite_count=1,
        rule_version=active.version,
        draft_hash=draft_hash,
        evidence=refs,
        audit=_audit("rewritten", reasons, 1, active.version, draft_hash),
    )


def _audit(action: str, reasons: list[str], rewrites: int, version: str, draft_hash: str) -> dict[str, Any]:
    return {
        "action": action,
        "reason_codes": reasons,
        "rule_version": version,
        "rewrite_count": rewrites,
        "draft_hash": draft_hash,
    }


def build_compliance_graph(policy: CompliancePolicy | None = None, model: Any = None):
    """编译合规子图；输出 ``compliance`` 决策。"""
    from langgraph.graph import END, START, StateGraph
    from typing_extensions import TypedDict

    from finance_agent.orchestrator.nodes.compliance import make_review_node

    active = policy or default_policy()

    class ComplianceState(TypedDict, total=False):
        draft: str
        evidence: list[dict[str, Any]]
        compliance: dict[str, Any]

    review = make_review_node(active, model)

    graph = StateGraph(ComplianceState)
    graph.add_node("review", review)
    graph.add_edge(START, "review")
    graph.add_edge("review", END)
    return graph.compile()


def compliance_run_status(action: str) -> RunStatus:
    return RunStatus.COMPLETED if action in {"passed", "rewritten", "audited"} else RunStatus.FAILED


__all__ = [
    "BLOCKED_RESPONSE",
    "RULE_VERSION",
    "CompliancePolicy",
    "ComplianceResult",
    "EvidenceRef",
    "always_reject_policy",
    "build_compliance_graph",
    "default_policy",
    "run_compliance",
]
