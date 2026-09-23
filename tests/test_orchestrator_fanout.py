"""统一调度回归：跨领域任务经 Plan-and-Execute 的 Send 调度、reducer 与旧旁路清零。

V2 中所有领域任务统一由 ``orchestrator.graphs.plan_execute_graph`` 调度（LangGraph ``Send``），
股票、市场、产品使用同一协议，不存在领域专用旁路；旧的 DAG 调度器已删除。
"""

from __future__ import annotations

from finance_agent.orchestrator.contracts import (
    BusinessDomain,
    DomainOutcome,
    ExecutionPlan,
    PlanTask,
)
from finance_agent.orchestrator.graphs.plan_execute_graph import (
    dispatch_ready_tasks,
    run_plan_execute,
)
from finance_agent.orchestrator.runtime.state import dedupe_concat, merge_dict


def _task(task_id: str, *, depends_on=None, domain: str = "stock_research") -> PlanTask:
    return PlanTask(
        task_id=task_id, domain=domain, goal=task_id, instruction=task_id,
        depends_on=list(depends_on or []), expected_output="domain_outcome",
    )


def test_only_ready_tasks_are_dispatched_via_send():
    plan = ExecutionPlan(tasks=[_task("a"), _task("b", depends_on=["a"], domain="product_research")])
    state = {
        "plan": plan.model_dump(mode="json"),
        "task_results": {},
        "thread_id": "v1:CUST1:conv-1",
    }

    sends = dispatch_ready_tasks(state)

    assert [send.arg["task_id"] for send in sends] == ["a"]
    assert all(send.node == "domain_worker" for send in sends)


def test_multi_domain_plan_runs_each_domain_task_once():
    seen: list[str] = []

    def domain_runner(context):
        seen.append(context.task.domain.value)
        return DomainOutcome(
            task_id=context.task.task_id, domain=context.task.domain,
            status="success", summary=f"{context.task.task_id} 完成",
        )

    plan = ExecutionPlan(tasks=[
        _task("t1", domain="stock_research"),
        _task("t2", domain="product_research"),
    ])
    result = run_plan_execute(
        domain_runner=domain_runner, initial_plan=plan,
        thread_id="v1:CUST1:conv-1", run_id="run-1",
        customer_id="CUST1", conversation_id="conv-1", user_message="复合请求",
    )

    assert sorted(seen) == ["product_research", "stock_research"]
    assert set(result["task_results"]) == {"t1", "t2"}
    assert result["run_status"] == "completed"


def test_reducers_merge_dicts_and_dedupe_lists():
    """最小 reducer：映射按 key 合并，列表按身份去重。"""
    assert merge_dict({"a": {"x": 1}}, {"a": {"y": 2}, "b": 3}) == {"a": {"x": 1, "y": 2}, "b": 3}
    assert dedupe_concat([{"fact_id": "f1"}, {"fact_id": "f2"}], [{"fact_id": "f1"}]) == [
        {"fact_id": "f1"}, {"fact_id": "f2"},
    ]


def test_legacy_scheduler_and_parallel_bypass_are_gone():
    """回归护栏：旧 DAG 调度器、Send 分片旁路与旧主图不得复活。"""
    import importlib

    for legacy in (
        "finance_agent.orchestrator.scheduler",
        "finance_agent.orchestrator.context_builder",
        "finance_agent.orchestrator.slots",
        "finance_agent.agents.supervisor",
        "finance_agent.agents.stock_analysis",
        "finance_agent.agents.market_insight",
        "finance_agent.agents.product_analysis",
        "finance_agent.agents.casual_chat",
        "finance_agent.agents.base",
    ):
        try:
            importlib.import_module(legacy)
        except ModuleNotFoundError:
            continue
        raise AssertionError(f"遗留模块仍存在：{legacy}")

    import finance_agent.orchestrator.orchestrator as module

    source = open(module.__file__, encoding="utf-8").read()
    for token in ("_build_graph", "_handle_message_legacy", "run_task_dag",
                  "ORCHESTRATION_V2_ENABLED", "StockAnalysisAgent", "ManagerAgent"):
        assert token not in source, f"旧编排残留：{token}"
