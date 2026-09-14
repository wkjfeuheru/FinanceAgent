"""Plan-and-Execute：计划校验、Send 就绪调度、依赖传递与重规划。"""

from __future__ import annotations

from finance_agent.orchestrator.contracts import (
    BusinessDomain,
    DomainOutcome,
    ExecutionPlan,
    PlanTask,
)
from finance_agent.orchestrator.plan_execute import (
    PLAN_TASK_LIMIT,
    build_plan_execute_graph,
    deterministic_planner,
    dispatch_ready_tasks,
    evaluate_plan_results,
    run_plan_execute,
    validate_execution_plan,
)


def _task(task_id: str, *, depends_on=None, domain: str = "stock_research") -> PlanTask:
    return PlanTask(
        task_id=task_id,
        domain=domain,
        goal=f"目标 {task_id}",
        instruction=f"说明 {task_id}",
        depends_on=list(depends_on or []),
        expected_output="domain_outcome",
    )


def _plan_state(tasks):
    return {
        "plan": ExecutionPlan(tasks=tasks).model_dump(mode="json"),
        "task_results": {},
        "thread_id": "v1:CUST1:conv-1",
        "run_id": "run-1",
    }


def test_plan_rejects_more_than_eight_tasks():
    plan = ExecutionPlan(tasks=[_task(str(i)) for i in range(PLAN_TASK_LIMIT + 1)])

    result = validate_execution_plan(plan)

    assert result.valid is False
    assert result.error.code == "plan_task_limit"


def test_plan_rejects_duplicate_ids_and_unknown_dependency():
    duplicate = ExecutionPlan(tasks=[_task("a"), _task("a")])
    assert validate_execution_plan(duplicate).error.code == "plan_duplicate_task_id"

    unknown_dep = ExecutionPlan(tasks=[_task("a", depends_on=["ghost"])])
    assert validate_execution_plan(unknown_dep).error.code == "plan_unknown_dependency"


def test_plan_rejects_dependency_cycle():
    cycle = ExecutionPlan(
        tasks=[_task("a", depends_on=["b"]), _task("b", depends_on=["a"])]
    )

    assert validate_execution_plan(cycle).error.code == "plan_dependency_cycle"


def test_plan_rejects_missing_expected_output():
    task = _task("a")
    plan = ExecutionPlan(tasks=[task.model_copy(update={"expected_output": ""})])

    assert validate_execution_plan(plan).error.code == "plan_missing_expected_output"


def test_only_ready_tasks_are_sent_and_dependencies_receive_results():
    state = _plan_state([_task("a"), _task("b", depends_on=["a"])])

    sends = dispatch_ready_tasks(state)

    assert [send.arg["task_id"] for send in sends] == ["a"]


def test_dependent_task_receives_upstream_outcome_and_shared_thread_id():
    state = _plan_state([_task("a"), _task("b", depends_on=["a"])])
    state["task_results"] = {
        "a": DomainOutcome(
            task_id="a", domain=BusinessDomain.STOCK_RESEARCH, status="success", summary="a 完成。"
        ).model_dump(mode="json")
    }

    send = dispatch_ready_tasks(state)[0]

    assert send.arg["task_id"] == "b"
    assert send.arg["thread_id"] == "v1:CUST1:conv-1"
    assert send.arg["upstream_results"]["a"]["summary"] == "a 完成。"


def test_failed_dependency_blocks_dependent_without_failing_plan():
    state = _plan_state([_task("a"), _task("b", depends_on=["a"])])
    state["task_results"] = {
        "a": DomainOutcome(
            task_id="a", domain=BusinessDomain.STOCK_RESEARCH, status="failed", summary=""
        ).model_dump(mode="json")
    }

    assert dispatch_ready_tasks(state) == []
    # 仍有任务但无就绪项，且还有重规划预算 -> 请求重规划。
    assert evaluate_plan_results(state).action == "replan"


def test_evaluate_finishes_when_all_tasks_complete():
    state = _plan_state([_task("a")])
    state["task_results"] = {
        "a": DomainOutcome(
            task_id="a", domain=BusinessDomain.STOCK_RESEARCH, status="success", summary="ok"
        ).model_dump(mode="json")
    }

    assert evaluate_plan_results(state).action == "finish"


def test_run_plan_execute_runs_dependency_order_and_merges_results():
    seen: list[str] = []

    def domain_runner(context):
        seen.append(context.task.task_id)
        upstream = {key: value.summary for key, value in context.upstream_results.items()}
        return DomainOutcome(
            task_id=context.task.task_id,
            domain=context.task.domain,
            status="success",
            summary=f"{context.task.task_id} 完成 upstream={upstream}",
        )

    plan = ExecutionPlan(
        tasks=[
            _task("a"),
            _task("b", depends_on=["a"], domain="market_insight"),
        ]
    )
    result = run_plan_execute(
        domain_runner=domain_runner,
        initial_plan=plan,
        thread_id="v1:CUST1:conv-1",
        run_id="run-1",
        customer_id="CUST1",
        conversation_id="conv-1",
        user_message="市场情绪和基金产品怎么搭配",
    )

    assert seen == ["a", "b"]
    assert result["run_status"] == "completed"
    assert "upstream={'a': 'a 完成 upstream={}'}" in result["task_results"]["b"]["summary"]


def test_plan_execute_graph_dispatches_via_send():
    seen: list[str] = []

    def domain_runner(context):
        seen.append(context.task.task_id)
        return DomainOutcome(
            task_id=context.task.task_id,
            domain=context.task.domain,
            status="success",
            summary=f"{context.task.task_id} 完成",
        )

    graph = build_plan_execute_graph(domain_runner=domain_runner)
    result = graph.invoke(
        {
            "user_message": "跨领域请求",
            "domains": ["stock_research", "product_research"],
            "thread_id": "v1:CUST1:conv-1",
            "run_id": "run-1",
        }
    )

    assert sorted(seen) == ["plan:product_research", "plan:stock_research"]
    assert set(result["task_results"]) == {"plan:product_research", "plan:stock_research"}


def test_deterministic_planner_creates_one_task_per_domain():
    plan = deterministic_planner(
        {"user_message": "复合请求"},
        [BusinessDomain.STOCK_RESEARCH, BusinessDomain.PRODUCT_RESEARCH],
    )

    assert [task.domain for task in plan.tasks] == [
        BusinessDomain.STOCK_RESEARCH,
        BusinessDomain.PRODUCT_RESEARCH,
    ]
    assert validate_execution_plan(plan).valid
