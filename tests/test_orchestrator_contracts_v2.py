import pytest
from pydantic import ValidationError

from finance_agent.orchestrator.contracts import (
    REACT_STEPS_HARD_CAP,
    AsyncJobRef,
    BusinessDomain,
    ComplianceDecision,
    ExecutionMode,
    NodeError,
    RunBudgets,
)
from finance_agent.orchestrator.thread_key import build_thread_id, parse_thread_id


def test_thread_key_is_customer_scoped_and_round_trips():
    """A thread key must preserve both the authenticated customer and conversation."""
    value = build_thread_id("CUST000001", "conv-1")

    assert value == "v1:CUST000001:conv-1"
    assert parse_thread_id(value) == ("CUST000001", "conv-1")


def test_budget_rejects_values_above_confirmed_limits():
    """The confirmed ReAct ceiling must be enforced at the contract boundary."""
    assert RunBudgets().react_steps == 4

    # 上限放宽为全局硬天花板（默认值的 2 倍冗余）：环境变量可在其内调节，
    # 但越过天花板必须被拒绝——预算不能被配置成失去防护意义。
    assert RunBudgets(react_steps=REACT_STEPS_HARD_CAP).react_steps == REACT_STEPS_HARD_CAP

    with pytest.raises(ValidationError):
        RunBudgets(react_steps=REACT_STEPS_HARD_CAP + 1)


@pytest.mark.parametrize(
    ("provided", "expected"),
    [
        ("stock_research", BusinessDomain.STOCK_RESEARCH),
        ("market_insight", BusinessDomain.MARKET_INSIGHT),
        ("product_research", BusinessDomain.PRODUCT_RESEARCH),
    ],
)
def test_business_domain_accepts_only_the_confirmed_domains(provided, expected):
    """Routing must retain each of the three approved business domains."""
    assert BusinessDomain(provided) is expected


def test_execution_and_operational_contracts_preserve_safe_runtime_data():
    """Downstream nodes need typed operational decisions and safe error details."""
    job = AsyncJobRef(job_id="job-1", kind="quant", status="queued", task_id="task-1")
    compliance = ComplianceDecision(
        action="rewritten",
        response="已改写的答复",
        reason_codes=["risk_disclosure"],
        rewrite_count=1,
    )
    error = NodeError(
        code="UPSTREAM_TIMEOUT",
        category="transient",
        retryable=True,
        safe_message="上游服务暂不可用",
        internal_ref="trace-1",
    )

    assert ExecutionMode.DOMAIN_REACT.value == "domain_react"
    assert job.status == "queued"
    assert compliance.action == "rewritten"
    assert error.retryable is True


def test_status_mappings_are_centralized_and_aligned_with_run_status_enum():
    """状态映射集中在契约层且与 RunStatus 枚举同源，拼写漂移在此暴露。"""
    from finance_agent.contracts import RunStatus
    from finance_agent.orchestrator.contracts import (
        DEFAULT_INTENT_DOMAIN_STATUS,
        DEFAULT_JOB_RUN_STATUS,
        DEGRADED_INTENT_STATUSES,
        DEGRADED_RUN_STATUSES,
        DOMAIN_STATUS_TO_RUN_STATUS,
        INTENT_STATUS_TO_DOMAIN_STATUS,
        JOB_STATUS_TO_RUN_STATUS,
    )

    # 领域结论状态映射覆盖 DomainOutcome.status 的全部 Literal（processing 为
    # 异步量化专属，RunStatus 中无同名成员）。
    assert set(DOMAIN_STATUS_TO_RUN_STATUS) == {"success", "partial", "processing", "failed"}
    assert set(DOMAIN_STATUS_TO_RUN_STATUS.values()) - {"processing"} <= {
        status.value for status in RunStatus
    }
    # 任务状态映射与 RunStatus 同源。
    assert set(JOB_STATUS_TO_RUN_STATUS.values()) == {
        DEFAULT_JOB_RUN_STATUS, RunStatus.COMPLETED.value, RunStatus.FAILED.value,
        RunStatus.CANCELLED.value,
    }
    # 意图状态映射语义独立于运行状态映射（前者是意图结果→领域结论）。
    assert INTENT_STATUS_TO_DOMAIN_STATUS["degraded"] == DEFAULT_INTENT_DOMAIN_STATUS == "partial"
    assert INTENT_STATUS_TO_DOMAIN_STATUS["failed"] == "failed"
    assert DEGRADED_INTENT_STATUSES == frozenset({"degraded", "failed"})
    assert DEGRADED_RUN_STATUSES == {RunStatus.FAILED.value, RunStatus.PARTIAL.value}
