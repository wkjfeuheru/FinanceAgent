import pytest
from pydantic import ValidationError

from finance_agent.orchestrator.contracts import (
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

    with pytest.raises(ValidationError):
        RunBudgets(react_steps=5)


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
