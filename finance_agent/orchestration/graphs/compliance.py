"""统一合规出口（设计 §6.8、§12）。

所有可见输出（成功、部分、降级、恢复后）都必须经过本子图：

    draft -> deterministic_policy_check -> semantic_policy_check
          -> pass -> final
          -> rewrite once -> recheck -> pass
                                   -> block

改写不得改变事实、数值和引用，只能删除违规表达、调整措辞或补充风险提示。
复检仍失败时 fail-closed。审计保存原因码、规则版本、草稿哈希与最终动作，
不向前端暴露内部违规草稿。

## 受信语料的**句级**豁免

FAQ 原文（经人工审核的知识库）里的风险词汇是合法且必需的表达：把"什么是操纵
市场？"删成"什么是？"会把答案变成病句。因此受信内容只审计、不改写、不拦截。

判定不是整轮开关，而是**逐句向量相似度**：对回复分句，句子与命中的 FAQ 原文
做余弦相似度比较，只有确实有原文支撑的句子获得豁免；模型在原文之外自由发挥的
句子照常走确定性检查与改写。相似度不可计算（未注入 embedding）时**不放行任何
豁免**——宁可多改一次，不可少查一句。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Sequence

from pydantic import BaseModel, Field

from finance_agent.shared.contracts import RunStatus
from finance_agent.safety.output_policy import check_sensitive_words

logger = logging.getLogger(__name__)

RULE_VERSION = "compliance/v1"
RISK_DISCLAIMER = "以上内容仅供参考，不构成投资建议；市场有风险，投资需谨慎。"
BLOCKED_RESPONSE = "抱歉，本次回复未能通过合规校验，已为您拦截。请换一种方式提问。"

#: 句级受信判定的默认相似度阈值。FAQ 检索侧的经验值（同义改写提问约 0.61~0.77、
#: 正确条目 0.82）表明 0.82 能把"改写后的同一句话"与"沾边但不支撑"的句子区分开；
#: 阈值经配置注入，可用 evals 校准。
TRUST_SIMILARITY_THRESHOLD = 0.82
#: 参与受信判定的最短片段（去空白后）：过短的片段（"好。""谢谢。"）语义不可比，
#: 一律按非受信处理——它们本来也不含需要豁免的规则词汇。
_MIN_JUDGEABLE_CHARS = 6

_NUMBER = re.compile(r"\d+(?:\.\d+)?")
#: 片段分隔：中文/英文句末标点与换行。分隔符本身留在片段里，保证重组逐字还原。
_SEGMENT_RE = re.compile(r"[。！？!?]|\n+")


class ComplianceUnavailable(RuntimeError):
    """合规校验能力不可用（如语义校验模型调用失败）。

    必须 fail-closed：调用方（合规节点）据此拦截未经校验的草稿，而不是放行。
    """


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
    #: 本轮被判定为受信（豁免改写）的片段数，以及判定阈值：审计可复现的依据。
    trusted_spans: int = 0
    similarity_threshold: float = 0.0


@dataclass
class CompliancePolicy:
    """确定性规则 + 可选语义校验 + 一次受约束改写的策略集合。

    ``rewrite``：整段改写（可追加免责声明等尾部内容）。
    ``redact``：**片段级**去违规（不追加尾部），用于句级豁免下的逐句改写；
    未提供时回退到 ``rewrite``（自定义策略可能因此给每个片段都追加尾部）。
    """

    version: str = RULE_VERSION
    check: Callable[[str], list[str]] = field(default_factory=lambda: _default_check)
    semantic_check: Callable[[str], list[str]] | None = None
    rewrite: Callable[[str], str | None] | None = None
    redact: Callable[[str], str | None] | None = None


def _default_check(text: str) -> list[str]:
    return [f"sensitive_word:{word}" for word in check_sensitive_words(text or "")]


def _strip_violations(text: str) -> str:
    """删除命中的违规表达、收敛空白；不追加任何尾部内容。"""
    rewritten = text or ""
    for word in check_sensitive_words(rewritten):
        rewritten = rewritten.replace(word, "")
    return re.sub(r"[ \t]{2,}", " ", rewritten).strip()


def _default_rewrite(text: str) -> str:
    """删除命中的违规表达，其余（含数值与结构）保持不变，并补一次风险提示。"""
    rewritten = _strip_violations(text)
    if rewritten and RISK_DISCLAIMER not in rewritten:
        rewritten = f"{rewritten}\n\n{RISK_DISCLAIMER}"
    return rewritten


def default_policy() -> CompliancePolicy:
    return CompliancePolicy(
        version=RULE_VERSION,
        check=_default_check,
        semantic_check=None,
        rewrite=_default_rewrite,
        redact=_strip_violations,
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


# ── 句级受信判定 ──────────────────────────────────────────────────────


def split_segments(text: str) -> list[tuple[str, bool]]:
    """把文本切成 ``(片段, 是否参与受信判定)``；按序拼接可逐字还原原文。"""
    value = text or ""
    segments: list[tuple[str, bool]] = []
    start = 0
    for match in _SEGMENT_RE.finditer(value):
        segments.append((value[start:match.end()], False))
        start = match.end()
    if start < len(value):
        segments.append((value[start:], False))
    return [
        (span, len(span.strip()) >= _MIN_JUDGEABLE_CHARS) for span, _ in segments
    ]


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """余弦相似度；维度不一致或零向量返回 0（视为不相似）。"""
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = sum(a * a for a in left) ** 0.5
    right_norm = sum(b * b for b in right) ** 0.5
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def mark_trusted_segments(
    segments: list[tuple[str, bool]],
    sources: Sequence[str],
    embed: Any,
    threshold: float,
) -> list[bool]:
    """逐片段判定是否"有受信原文支撑"。

    ``embed`` 需实现 ``embed_query(text) -> list[float]``（FAQ 侧的 embedding seam）。
    未提供 ``embed``、没有原文、或向量化失败时返回全 False：**不放行任何豁免**。
    """
    if embed is None or not sources:
        return [False] * len(segments)
    try:
        source_vectors = [embed.embed_query(str(source)) for source in sources if str(source).strip()]
    except Exception:  # noqa: BLE001 - 向量化不可用按"不放行豁免"处理（fail-closed）
        logger.warning("trust_embedding_failed", exc_info=True)
        return [False] * len(segments)
    if not source_vectors:
        return [False] * len(segments)

    flags: list[bool] = []
    for span, judgeable in segments:
        if not judgeable:
            flags.append(False)
            continue
        try:
            vector = embed.embed_query(span.strip())
        except Exception:  # noqa: BLE001
            logger.warning("trust_embedding_failed span=%s", span[:20], exc_info=True)
            flags.append(False)
            continue
        best = max(cosine_similarity(vector, source) for source in source_vectors)
        flags.append(best >= threshold)
    return flags


def build_model_semantic_check(
    model: Any,
    *,
    prompt: str | None = None,
) -> Callable[[str], list[str]]:
    """把 chat model 适配为**只输出违规码**的语义校验器。

    刻意不让模型改写文本：模型改写会把不确定性直接引入用户可见内容。它只回答
    "有没有违规、属于哪一类"，改写仍由确定性规则完成。调用失败抛
    ``ComplianceUnavailable``，由调用方 fail-closed 拦截。
    """
    from finance_agent.infrastructure.llm.factory import build_chat_model_callable

    call = build_chat_model_callable(model, require_json=True)
    template = prompt or _SEMANTIC_CHECK_PROMPT

    def check(text: str) -> list[str]:
        content = str(text or "").strip()
        if not content:
            return []
        try:
            raw = call([{"role": "system", "content": template.format(text=content)}])
            payload = json.loads(raw) if isinstance(raw, str) else raw
        except Exception as exc:  # noqa: BLE001 - 语义校验不可用必须 fail-closed
            raise ComplianceUnavailable("semantic_check_failed") from exc
        items = payload.get("violations") if isinstance(payload, dict) else None
        codes: list[str] = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code") or "").strip()
            if code:
                codes.append(f"semantic:{code}")
        return list(dict.fromkeys(codes))

    return check


_SEMANTIC_CHECK_PROMPT = """你是投顾回复的合规审查器。只判断给定文本是否包含下列违规表达，
不回答问题、不改写文本、不解释理由。

违规类别（code）：
- guaranteed_return：承诺/暗示收益或保本（"保证收益""稳赚不赔""必涨"）
- trade_solicitation：诱导交易或给出买卖指令（"建议买入""赶紧加仓""清仓"）
- stock_pitch：以推荐个股为目的的话术（点名个股并给出推荐倾向）
- insider：声称内幕消息或未公开信息
- proxy_trading：代客操作、代客下单

只输出 JSON：{{"violations": [{{"code": "...", "quote": "原文片段"}}]}}
没有任何违规时输出 {{"violations": []}}。

待审查文本：
{text}"""


def run_compliance(
    *,
    draft: str,
    evidence: list[EvidenceRef] | list[dict[str, Any]] | None = None,
    policy: CompliancePolicy | None = None,
    model: Any = None,
    audit_only: bool = False,
    rewrite_budget: int | None = None,
    trusted_sources: Sequence[str] | None = None,
    embed: Any = None,
    trust_threshold: float = TRUST_SIMILARITY_THRESHOLD,
    semantic_check: Callable[[str], list[str]] | None = None,
) -> ComplianceResult:
    """执行确定性规则、可选语义校验、一次改写与复检。

    ``audit_only=True`` 用于内容整体来自受信来源但**没有原文可比对**的场景
    （旧口径）：仍然执行检查并把命中项写入审计，但不改写、不拦截。

    ``trusted_sources`` + ``embed`` 提供时走**句级**受信判定：只有与原文相似度
    达标的句子被豁免，其余句子照常检查/改写；任一非受信片段复检失败即整轮
    fail-closed（不交付半合规内容）。

    ``rewrite_budget`` 来自 ``RunBudgets.compliance_rewrites``（None 时取
    config 默认）。为 0 时不尝试改写、直接 fail-closed——预算收紧到零时
    宁可拦截也不放行未校验内容。
    """
    if rewrite_budget is None:
        from finance_agent.infrastructure import settings as config

        rewrite_budget = config.ORCHESTRATION_COMPLIANCE_REWRITES

    active = policy or default_policy()
    refs = [item if isinstance(item, EvidenceRef) else EvidenceRef.model_validate(item) for item in (evidence or [])]
    draft_hash = _draft_hash(draft)

    def _reasons(text: str) -> list[str]:
        found = list(active.check(text))
        if active.semantic_check is not None:
            found += list(active.semantic_check(text))
        if semantic_check is not None:
            found += list(semantic_check(text))
        return found

    if audit_only and not trusted_sources:
        reasons = _reasons(draft)
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

    segments = split_segments(draft)
    trusted = mark_trusted_segments(segments, list(trusted_sources or []), embed, trust_threshold)
    trusted_count = sum(1 for flag in trusted if flag)

    if trusted_count == 0:
        # 无豁免：与既有整段路径完全一致（确定性检查 → 一次改写 → 复检）。
        result = _run_untrusted(
            draft=draft,
            reasons=_reasons(draft),
            active=active,
            rewrite_budget=rewrite_budget,
            draft_hash=draft_hash,
            refs=refs,
            rewrite_target=draft,
        )
        result.similarity_threshold = float(trust_threshold) if trusted_sources else 0.0
        return result

    # 句级豁免：受信片段逐字保留，非受信片段照常检查/改写/复检。
    untrusted_text = "".join(span for (span, _), flag in zip(segments, trusted) if not flag)
    reasons = _reasons(untrusted_text)
    if not reasons:
        return ComplianceResult(
            action="audited",
            response=draft,
            reason_codes=[],
            rewrite_count=0,
            rule_version=active.version,
            draft_hash=draft_hash,
            evidence=refs,
            audit=_audit("audited", [], 0, active.version, draft_hash),
            trusted_spans=trusted_count,
            similarity_threshold=float(trust_threshold),
        )

    if rewrite_budget < 1:
        return ComplianceResult(
            action="blocked",
            response=BLOCKED_RESPONSE,
            reason_codes=reasons,
            rewrite_count=0,
            rule_version=active.version,
            draft_hash=draft_hash,
            evidence=refs,
            audit=_audit("blocked", reasons, 0, active.version, draft_hash),
            trusted_spans=trusted_count,
            similarity_threshold=float(trust_threshold),
        )

    redact = active.redact or active.rewrite
    if redact is None:
        return ComplianceResult(
            action="blocked",
            response=BLOCKED_RESPONSE,
            reason_codes=reasons,
            rewrite_count=0,
            rule_version=active.version,
            draft_hash=draft_hash,
            evidence=refs,
            audit=_audit("blocked", reasons, 0, active.version, draft_hash),
            trusted_spans=trusted_count,
            similarity_threshold=float(trust_threshold),
        )

    parts: list[str] = []
    rewritten_untrusted: list[str] = []
    for (span, _), is_trusted in zip(segments, trusted):
        if is_trusted:
            parts.append(span)
            continue
        redacted = redact(span)
        if redacted is None:
            redacted = ""
        rewritten_untrusted.append(redacted)
        parts.append(redacted)
    rebuilt = "".join(parts)
    if RISK_DISCLAIMER not in rebuilt and rebuilt.strip():
        rebuilt = f"{rebuilt.strip()}\n\n{RISK_DISCLAIMER}"

    rewritten_text = "".join(rewritten_untrusted)
    if not _preserves_facts(untrusted_text, rewritten_text):
        return ComplianceResult(
            action="blocked",
            response=BLOCKED_RESPONSE,
            reason_codes=reasons + ["rewrite_changed_facts"],
            rewrite_count=1,
            rule_version=active.version,
            draft_hash=draft_hash,
            evidence=refs,
            audit=_audit("blocked", reasons, 1, active.version, draft_hash),
            trusted_spans=trusted_count,
            similarity_threshold=float(trust_threshold),
        )

    recheck = _reasons(rewritten_text)
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
            trusted_spans=trusted_count,
            similarity_threshold=float(trust_threshold),
        )

    return ComplianceResult(
        action="rewritten",
        response=rebuilt,
        reason_codes=reasons,
        rewrite_count=1,
        rule_version=active.version,
        draft_hash=draft_hash,
        evidence=refs,
        audit=_audit("rewritten", reasons, 1, active.version, draft_hash),
        trusted_spans=trusted_count,
        similarity_threshold=float(trust_threshold),
    )


def _run_untrusted(
    *,
    draft: str,
    reasons: list[str],
    active: CompliancePolicy,
    rewrite_budget: int,
    draft_hash: str,
    refs: list[EvidenceRef],
    rewrite_target: str,
) -> ComplianceResult:
    """无豁免（或整段等价）时的既有路径：检查 → 一次改写 → 复检。"""
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

    rewritten = active.rewrite(rewrite_target)
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


def make_review_node(
    policy: CompliancePolicy,
    model: Any,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """review 节点工厂；``policy``/``model`` 由 ``build_compliance_graph`` 注入。"""

    def review(state: dict[str, Any]) -> dict[str, Any]:
        result = run_compliance(
            draft=str(state.get("draft", "")),
            evidence=list(state.get("evidence", []) or []),
            policy=policy,
            model=model,
        )
        return {"compliance": result.model_dump(mode="json")}

    return review


def build_compliance_graph(policy: CompliancePolicy | None = None, model: Any = None):
    """编译合规子图；输出 ``compliance`` 决策。"""
    from langgraph.graph import END, START, StateGraph
    from typing_extensions import TypedDict

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
    "TRUST_SIMILARITY_THRESHOLD",
    "CompliancePolicy",
    "ComplianceResult",
    "ComplianceUnavailable",
    "EvidenceRef",
    "always_reject_policy",
    "build_compliance_graph",
    "build_model_semantic_check",
    "cosine_similarity",
    "default_policy",
    "make_review_node",
    "mark_trusted_segments",
    "run_compliance",
    "split_segments",
]
