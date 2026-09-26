"""运行预算（``RunBudgets`` / ``OrchestrationSettings``）与预算实际接线的边界测试。

架构变更后的删除项（均已在下方注明，不再有替代实现）：

- ``ExecutionProfile`` 契约整体删除：``react`` / ``plan_execute`` 两种模式的显式
  配置随 ``plan_execute`` 模块一起移除（专家统一为 ReAct，跨领域由根图 ``Send``
  扇出），因此"模式不变量"测试已无对应行为。
- ``plan_execute._plan_task_limit`` / ``_replan_limit`` 随模块删除；领域扇出上限
  现在由 ``RunBudgets.max_domains`` 承载，接线断言见下。
- ``finance_agent/orchestration/runtime/operations.py`` 的 operation 注册表
  （``OperationRegistry`` / ``default_operation_registry``）已随子意图体系删除：
  专家 ReAct 自主决定领域内分析路径，不再由注册表登记"领域 → 模式"。

保留：``RunBudgets`` 的单一配置源与硬上限契约、预算实际接线的边界测试
（会话步数、合规改写预算），以及 ``OrchestrationSettings`` 的
``turn_timeout >= turn_deadline`` 不变量。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from finance_agent.orchestration.budgets import (
    CLARIFY_ROUNDS_HARD_CAP,
    COMPLIANCE_REWRITES_HARD_CAP,
    DOMAINS_HARD_CAP,
    GRAPH_STEPS_HARD_CAP,
    REACT_STEPS_HARD_CAP,
    RunBudgets,
)


# ── RunBudgets：单一配置源与全局硬上限 ───────────────────────────────────


def test_run_budgets_from_config_reads_environment(monkeypatch):
    """config.ORCHESTRATION_* 是唯一数值源，环境变量变更必须体现在预算上。"""
    import finance_agent.infrastructure.settings as config

    monkeypatch.setattr(config, "ORCHESTRATION_REACT_STEPS", 6)
    monkeypatch.setattr(config, "ORCHESTRATION_MAX_DOMAINS", 3)
    monkeypatch.setattr(config, "ORCHESTRATION_COMPLIANCE_REWRITES", 0)
    monkeypatch.setattr(config, "ORCHESTRATION_CLARIFY_ROUNDS", 3)
    monkeypatch.setattr(config, "ORCHESTRATION_GRAPH_STEPS", 40)
    monkeypatch.setattr(config, "ORCHESTRATION_TURN_DEADLINE", 45.0)

    budgets = RunBudgets.from_config()

    assert budgets.react_steps == 6
    assert budgets.max_domains == 3
    assert budgets.compliance_rewrites == 0
    assert budgets.clarify_rounds == 3
    assert budgets.graph_steps == 40
    assert budgets.turn_deadline == 45.0


def test_run_budgets_rejects_values_beyond_hard_caps():
    with pytest.raises(ValidationError):
        RunBudgets(react_steps=REACT_STEPS_HARD_CAP + 1)
    with pytest.raises(ValidationError):
        RunBudgets(max_domains=DOMAINS_HARD_CAP + 1)
    with pytest.raises(ValidationError):
        RunBudgets(compliance_rewrites=COMPLIANCE_REWRITES_HARD_CAP + 1)
    with pytest.raises(ValidationError):
        RunBudgets(clarify_rounds=CLARIFY_ROUNDS_HARD_CAP + 1)
    with pytest.raises(ValidationError):
        RunBudgets(graph_steps=GRAPH_STEPS_HARD_CAP + 1)


# 已删除：``test_plan_task_limit_alias_follows_config`` 断言
# ``plan_execute._plan_task_limit()`` / ``_replan_limit()`` 直接读 config。
# 该模块（plan_execute / deterministic_planner / replan 预算）已整体删除：
# 领域扇出上限改由 ``RunBudgets.max_domains`` 承载（上面已覆盖接线）。


# ── OrchestrationSettings：整轮预算不变量 ────────────────────────────────


def test_orchestration_settings_rejects_turn_timeout_shorter_than_deadline():
    """等待上限不得短于执行上限。

    等待（API/SSE）比执行（图内整轮墙钟）更短，只会让用户先看到"超时"而执行线程
    仍在跑——这正是历史上"算好了却报超时"的成因，因此在此显式拒绝。
    """
    from finance_agent.infrastructure.settings import OrchestrationSettings

    with pytest.raises(ValidationError):
        OrchestrationSettings(turn_deadline=10, turn_timeout=5)


def test_orchestration_settings_accepts_timeout_equal_to_deadline():
    """边界：两者相等是允许的最小合法组合（不会误拒绝）。"""
    from finance_agent.infrastructure.settings import OrchestrationSettings

    settings = OrchestrationSettings(turn_deadline=10, turn_timeout=10)

    assert settings.turn_deadline == 10
    assert settings.turn_timeout == 10


# ── 预算接线：会话步数与合规改写预算实际生效 ─────────────────────────────


def _retriever():
    class _Retriever:
        def search(self, query):
            from finance_agent.domains.faq.contracts import FaqSearchResult
            return FaqSearchResult(status="not_found", matches=[])

    return _Retriever()


def test_conversation_respects_configured_react_steps(monkeypatch):
    """会话步数上限由配置决定（取 config.ORCHESTRATION_REACT_STEPS），而非硬编码。"""
    import finance_agent.infrastructure.settings as config
    from finance_agent.orchestration.graphs.conversation import run_conversation
    from tests.conftest import make_fake_tool_model, tool_call

    monkeypatch.setattr(config, "ORCHESTRATION_REACT_STEPS", 2)

    # 模型每轮都请求 faq_search：达到 2 次模型调用后由中间件截断。
    # 必须给每条 tool_call 唯一 id：复用同一条 AIMessage 会被循环判为同一轮。
    model = make_fake_tool_model([
        tool_call("faq_search", {"query": "x"}, call_id=f"c{i}") for i in range(6)
    ])
    result = run_conversation(_retriever(), model, user_message="随便问问")

    assert result["react_steps"] == 2
    assert result["status"] == "partial"
    assert "conversation_step_limit" in result["warnings"]


def test_compliance_rewrite_budget_zero_fails_closed():
    from finance_agent.orchestration.graphs.compliance import run_compliance

    # 命中敏感词但改写预算为 0：直接拦截，绝不放行未校验草稿。
    result = run_compliance(draft="这只股票保证收益。", rewrite_budget=0)

    assert result.action == "blocked"
    assert result.rewrite_count == 0
