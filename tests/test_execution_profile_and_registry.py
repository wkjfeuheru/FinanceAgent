"""统一图配置契约、运行预算与 operation 注册表的边界测试。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from finance_agent.orchestrator.contracts import (
    GRAPH_STEPS_HARD_CAP,
    PLAN_TASKS_HARD_CAP,
    REACT_STEPS_HARD_CAP,
    BusinessDomain,
    ExecutionProfile,
    RunBudgets,
)
from finance_agent.orchestrator.runtime.operations import OperationRegistry, default_operation_registry


# ── RunBudgets：单一配置源与全局硬上限 ───────────────────────────────────


def test_run_budgets_from_config_reads_environment(monkeypatch):
    """config.ORCHESTRATION_* 是唯一数值源，环境变量变更必须体现在预算上。"""
    import finance_agent.config as config

    monkeypatch.setattr(config, "ORCHESTRATION_REACT_STEPS", 6)
    monkeypatch.setattr(config, "ORCHESTRATION_PLAN_TASKS", 5)
    monkeypatch.setattr(config, "ORCHESTRATION_REPLANS", 1)
    monkeypatch.setattr(config, "ORCHESTRATION_COMPLIANCE_REWRITES", 0)
    monkeypatch.setattr(config, "ORCHESTRATION_GRAPH_STEPS", 40)

    budgets = RunBudgets.from_config()

    assert budgets.react_steps == 6
    assert budgets.plan_tasks == 5
    assert budgets.replans == 1
    assert budgets.compliance_rewrites == 0
    assert budgets.graph_steps == 40


def test_run_budgets_rejects_values_beyond_hard_caps():
    with pytest.raises(ValidationError):
        RunBudgets(react_steps=REACT_STEPS_HARD_CAP + 1)
    with pytest.raises(ValidationError):
        RunBudgets(plan_tasks=PLAN_TASKS_HARD_CAP + 1)
    with pytest.raises(ValidationError):
        RunBudgets(graph_steps=GRAPH_STEPS_HARD_CAP + 1)


def test_plan_task_limit_alias_follows_config(monkeypatch):
    """plan_execute 的上限取值函数必须直接读 config，不自带数值副本。"""
    import finance_agent.config as config
    import finance_agent.orchestrator.graphs.plan_execute_graph as plan_execute

    monkeypatch.setattr(config, "ORCHESTRATION_PLAN_TASKS", 3)
    monkeypatch.setattr(config, "ORCHESTRATION_REPLANS", 1)

    assert plan_execute._plan_task_limit() == 3
    assert plan_execute._replan_limit() == 1


# ── ExecutionProfile：模式不变量 ─────────────────────────────────────────


def test_execution_profile_accepts_valid_configs():
    react = ExecutionProfile(mode="react", max_steps=4, operation_scope="stock")
    plan = ExecutionProfile(
        mode="plan_execute", max_steps=8, replan_enabled=True,
        max_replans=2, operation_scope="cross_domain",
    )

    assert react.replan_enabled is False
    assert plan.max_replans == 2


@pytest.mark.parametrize(
    "kwargs",
    [
        # react 不得启用重规划
        dict(mode="react", max_steps=4, replan_enabled=True, max_replans=1, operation_scope="stock"),
        # react 必须是单领域范围
        dict(mode="react", max_steps=4, operation_scope="cross_domain"),
        # plan_execute 必须是跨领域范围
        dict(mode="plan_execute", max_steps=8, operation_scope="stock"),
        # 启用重规划必须给出至少一次预算
        dict(mode="plan_execute", max_steps=8, replan_enabled=True,
             max_replans=0, operation_scope="cross_domain"),
        # max_steps 不得低于 1
        dict(mode="react", max_steps=0, operation_scope="stock"),
    ],
)
def test_execution_profile_rejects_invalid_combinations(kwargs):
    with pytest.raises(ValidationError):
        ExecutionProfile(**kwargs)


# ── OperationRegistry：白名单是显式登记，非自由调用 ─────────────────────


def test_registry_covers_all_business_domains():
    registry = default_operation_registry()

    assert set(registry.domains()) == {
        BusinessDomain.STOCK_RESEARCH,
        BusinessDomain.MARKET_INSIGHT,
        BusinessDomain.PRODUCT_RESEARCH,
        BusinessDomain.ACCOUNT_PORTFOLIO,
    }


def test_registry_exposes_operation_names_and_modes():
    registry = default_operation_registry()

    assert "stock_research" in registry.operation_names(BusinessDomain.STOCK_RESEARCH)
    assert set(registry.modes(BusinessDomain.MARKET_INSIGHT)) >= {
        "market_overview", "market_sentiment", "capital_flow", "policy_impact",
    }
    assert registry.spec(BusinessDomain.PRODUCT_RESEARCH).default_mode == "product_lookup"


def test_registry_rejects_duplicate_domain_registration():
    registry = OperationRegistry(specs=[])
    from finance_agent.orchestrator.runtime.operations import DomainSpec

    spec = DomainSpec(
        domain=BusinessDomain.STOCK_RESEARCH,
        operations_factory=lambda deps=None: [],
        default_mode="single_analysis",
    )
    registry.register(spec)
    with pytest.raises(ValueError):
        registry.register(spec)


def test_registry_unknown_domain_raises():
    registry = OperationRegistry(specs=[])
    with pytest.raises(KeyError):
        registry.spec(BusinessDomain.STOCK_RESEARCH)


# ── 预算接线：react 步数与合规改写预算实际生效 ───────────────────────────


def test_conversation_respects_configured_react_steps(monkeypatch):
    import finance_agent.config as config
    from finance_agent.orchestrator.graphs.conversation_graph import run_conversation

    monkeypatch.setattr(config, "ORCHESTRATION_REACT_STEPS", 2)

    calls = {"n": 0}

    def always_tool(messages):
        calls["n"] += 1
        return '{"action": "tool", "tool_name": "faq_search", "tool_input": {"query": "x"}}'

    class _Retriever:
        def search(self, query):
            from finance_agent.faq.contracts import FaqSearchResult
            return FaqSearchResult(status="not_found", matches=[])

    result = run_conversation(
        _Retriever(), always_tool, user_message="随便问问",
    )

    # 步数上限由配置决定（2 步），而非硬编码 4。
    assert calls["n"] == 2
    assert result["react_steps"] == 2


def test_compliance_rewrite_budget_zero_fails_closed():
    from finance_agent.orchestrator.compliance import run_compliance

    # 命中敏感词但改写预算为 0：直接拦截，绝不放行未校验草稿。
    result = run_compliance(draft="这只股票保证收益。", rewrite_budget=0)

    assert result.action == "blocked"
    assert result.rewrite_count == 0
