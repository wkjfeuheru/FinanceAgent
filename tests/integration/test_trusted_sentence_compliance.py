"""合规出口的句级受信豁免、事实门禁与 fail-closed 语义。

产品口径：FAQ 原文（人工审核过）里的风险词汇是合法表达，删词会把答案改成病句；
但豁免**只覆盖确有原文支撑的句子**——模型在原文之外自由发挥的部分照常走确定性
检查与改写，且任一非受信片段复检失败就整轮拦截（不交付半合规内容）。
"""

from __future__ import annotations

import pytest

from finance_agent.orchestration.graphs.compliance import (
    BLOCKED_RESPONSE,
    ComplianceUnavailable,
    cosine_similarity,
    run_compliance,
    split_segments,
)

_RULE_SOURCE = "什么是操纵市场？操纵市场指通过虚假申报影响证券价格。"
_TRUSTED = "什么是操纵市场？"
_TRUSTED_DETAIL = "操纵市场指通过虚假申报影响证券价格。"


class _BucketEmbedder:
    """确定性假向量化：按"桶"给 one-hot 向量，同桶相似度 1、异桶 0。"""

    def __init__(self, buckets: dict[str, int], *, dimension: int = 8) -> None:
        self._buckets = buckets
        self._dimension = dimension

    def embed_query(self, text: str) -> list[float]:
        index = self._buckets.get(str(text).strip(), self._dimension - 1)
        vector = [0.0] * self._dimension
        vector[index] = 1.0
        return vector


def _embedder() -> _BucketEmbedder:
    return _BucketEmbedder({
        _RULE_SOURCE: 0,
        _TRUSTED: 0,
        _TRUSTED_DETAIL: 0,
        "该股保证收益 10%。": 1,
        "该股稳赚不赔。": 1,
    })


# ── 分句：必须能逐字还原 ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "draft",
    [
        "什么是操纵市场？\n操纵市场指虚假申报。\n该股保证收益 10%。",
        "第一句。第二句！第三句？",
        "没有句末标点的一整段文字",
        "换行结尾。\n\n\n后续段落。",
        "",
    ],
)
def test_segments_reassemble_the_original_text_exactly(draft):
    segments = split_segments(draft)

    assert "".join(span for span, _ in segments) == draft


# ── 相似度工具 ──────────────────────────────────────────────────────────


def test_cosine_similarity_handles_degenerate_inputs():
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine_similarity([], [1.0]) == 0.0
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0
    assert cosine_similarity([1.0], [1.0, 2.0]) == 0.0


# ── 句级豁免 ────────────────────────────────────────────────────────────


def test_trusted_sentences_are_exempt_while_untrusted_ones_are_rewritten():
    draft = f"{_TRUSTED}\n{_TRUSTED_DETAIL}\n该股保证收益 10%。"

    result = run_compliance(
        draft=draft, trusted_sources=[_RULE_SOURCE], embed=_embedder(),
    )

    assert result.action == "rewritten"
    assert result.trusted_spans == 2
    # 受信句逐字保留（否则"什么是操纵市场？"会变成病句）。
    assert _TRUSTED in result.response
    assert _TRUSTED_DETAIL in result.response
    # 非受信句照常改写。
    assert "保证收益" not in result.response
    assert "10%" in result.response, "改写不得丢失数值"
    assert result.audit["action"] == "rewritten"


def test_clean_response_with_trusted_sentences_is_audited_not_rewritten():
    result = run_compliance(
        draft=f"{_TRUSTED}\n{_TRUSTED_DETAIL}", trusted_sources=[_RULE_SOURCE], embed=_embedder(),
    )

    assert result.action == "audited"
    assert result.response == f"{_TRUSTED}\n{_TRUSTED_DETAIL}"
    assert result.trusted_spans == 2
    assert result.similarity_threshold > 0


def test_untrusted_fragment_failing_recheck_blocks_the_whole_response():
    """非受信片段复检不过 → 整轮 fail-closed（不交付半合规内容）。"""
    from finance_agent.orchestration.graphs.compliance import CompliancePolicy

    policy = CompliancePolicy(
        version="compliance/test",
        check=lambda text: ["semantic_violation"] if text.strip() else [],
        rewrite=lambda text: text,  # 改写后仍然违规
        redact=lambda text: text,
    )

    result = run_compliance(
        draft=f"{_TRUSTED}\n该股保证收益 10%。",
        policy=policy,
        trusted_sources=[_RULE_SOURCE],
        embed=_embedder(),
    )

    assert result.action == "blocked"
    assert result.response == BLOCKED_RESPONSE
    assert _TRUSTED not in result.response, "被拦截时不泄露任何草稿内容"


def test_without_embedding_no_exemption_is_granted():
    """相似度不可计算时不放行豁免：宁可多改一次，不可少查一句。"""
    draft = f"{_TRUSTED}\n{_TRUSTED_DETAIL}"

    result = run_compliance(draft=draft, trusted_sources=[_RULE_SOURCE], embed=None)

    assert result.trusted_spans == 0
    assert result.action in {"rewritten", "blocked"}
    assert result.response != draft


def test_threshold_governs_exemption():
    """阈值收紧到 1.0 以上时，连"同桶"的句子也不再被豁免。"""
    result = run_compliance(
        draft=f"{_TRUSTED}\n{_TRUSTED_DETAIL}",
        trusted_sources=[_RULE_SOURCE],
        embed=_BucketEmbedder({_RULE_SOURCE: 0, _TRUSTED: 1, _TRUSTED_DETAIL: 1}),
        trust_threshold=0.9,
    )

    assert result.trusted_spans == 0


def test_embedding_failure_grants_no_exemption():
    class _BrokenEmbedder:
        def embed_query(self, text: str) -> list[float]:
            raise RuntimeError("model unavailable")

    draft = f"{_TRUSTED}\n{_TRUSTED_DETAIL}"

    result = run_compliance(draft=draft, trusted_sources=[_RULE_SOURCE], embed=_BrokenEmbedder())

    assert result.trusted_spans == 0
    assert result.response != draft


# ── 语义校验不可用必须 fail-closed ──────────────────────────────────────


def test_semantic_check_failure_raises_for_caller_to_fail_closed():
    def broken(text: str) -> list[str]:
        raise ComplianceUnavailable("semantic_check_failed")

    with pytest.raises(ComplianceUnavailable):
        run_compliance(draft="正常内容。", semantic_check=broken)


def test_semantic_check_codes_are_merged_into_reasons():
    result = run_compliance(
        draft="该股保证收益 10%。",
        semantic_check=lambda text: ["semantic:guaranteed_return"],
    )

    assert result.action == "rewritten"
    assert "semantic:guaranteed_return" in result.reason_codes
