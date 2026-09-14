"""合规子图：规则命中、一次改写、复检拦截与事实/数值不变量。"""

from __future__ import annotations

from finance_agent.orchestrator.compliance import (
    BLOCKED_RESPONSE,
    EvidenceRef,
    always_reject_policy,
    build_compliance_graph,
    run_compliance,
)


def test_compliance_passes_clean_draft():
    result = run_compliance(draft="贵州茅台估值处于合理区间，仅供参考。")

    assert result.action == "passed"
    assert result.response == "贵州茅台估值处于合理区间，仅供参考。"


def test_compliance_rewrite_preserves_evidence_and_numbers():
    evidence = [EvidenceRef(fact_id="p/e", value=12.5)]

    final = run_compliance(draft="该股保证收益 12.5%，可以买入。", evidence=evidence)

    assert final.action == "rewritten"
    assert final.evidence == evidence
    assert "12.5" in final.response
    assert "保证收益" not in final.response
    assert final.rewrite_count == 1


def test_second_failed_compliance_review_blocks_output():
    assert run_compliance(draft="违规", policy=always_reject_policy()).action == "blocked"


def test_blocked_output_hides_internal_draft():
    result = run_compliance(draft="违规", policy=always_reject_policy())

    assert result.response == BLOCKED_RESPONSE
    assert "违规" not in result.response


def test_compliance_audit_records_reason_version_and_hash():
    result = run_compliance(draft="该股稳赚不赔。")

    assert result.audit["action"] in {"rewritten", "blocked"}
    assert result.audit["rule_version"]
    assert result.audit["draft_hash"]
    assert result.audit["reason_codes"]


def test_semantic_failure_blocks_even_after_rewrite():
    from finance_agent.orchestrator.compliance import CompliancePolicy

    policy = CompliancePolicy(
        version="compliance/test",
        check=lambda text: [],
        semantic_check=lambda text: ["semantic_violation"],
        rewrite=lambda text: text,  # 改写后仍命中语义规则
    )

    assert run_compliance(draft="任何内容", policy=policy).action == "blocked"


def test_compliance_graph_projects_decision():
    graph = build_compliance_graph()

    result = graph.invoke({"draft": "保证收益 8%", "evidence": []})

    assert result["compliance"]["action"] in {"rewritten", "blocked"}
    assert result["compliance"]["rewrite_count"] in {0, 1}
