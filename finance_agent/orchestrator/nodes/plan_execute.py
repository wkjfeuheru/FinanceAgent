"""Plan-and-Execute 子图的节点函数（规划、领域扇出、汇合、重规划）。

节点实现从 ``plan_execute.build_plan_execute_graph`` 的闭包迁出；Send 扇出、
计划校验与汇合判定仍是 ``plan_execute`` 模块的纯函数，节点在函数体内惰性
导入以避免循环依赖。
"""

from __future__ import annotations

import time
from typing import Any, Callable

from finance_agent.orchestrator.contracts import (
    BusinessDomain,
    DomainOutcome,
    DomainTaskContext,
    PlanTask,
)


def make_plan_node(
    planner: Callable[[dict[str, Any], list[BusinessDomain]], Any] | None,
    *,
    max_seconds: float = 0.0,
    task_limit: int = 0,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """规划节点工厂；``task_limit`` 为 0 时沿用模块默认上限。"""

    def plan_node(state: dict[str, Any]) -> dict[str, Any]:
        from finance_agent.orchestrator.graphs.plan_execute_graph import (
            _as_plan,
            deterministic_planner,
            validate_execution_plan,
        )

        plan = _as_plan(state.get("plan"))
        if plan is None:
            domains = [BusinessDomain(value) for value in state.get("domains", [])]
            plan = (planner or deterministic_planner)(state, domains)
        validation = validate_execution_plan(plan, task_limit=task_limit)
        if not validation.valid:
            return {
                "plan_error": validation.error.model_dump(mode="json") if validation.error else {},
                "warnings": [f"plan_invalid:{validation.error.code}"] if validation.error else [],
            }
        updates: dict[str, Any] = {"plan": validation.plan.model_dump(mode="json")}
        if max_seconds > 0:
            updates["deadline_monotonic"] = time.monotonic() + max_seconds
        return updates

    return plan_node


def after_plan(state: dict[str, Any]) -> str:
    """规划成功进入汇合，规划失败直接结束。"""
    return "finish" if state.get("plan_error") else "evaluate"


def make_domain_worker(
    domain_runner: Callable[[DomainTaskContext], DomainOutcome],
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Send 目标节点工厂：接收任务 payload（非图状态），执行单个领域任务。"""

    def domain_worker(payload: dict[str, Any]) -> dict[str, Any]:
        context = DomainTaskContext(
            task=PlanTask(
                task_id=payload["task_id"],
                domain=BusinessDomain(payload["domain"]),
                goal=payload["goal"],
                instruction=payload["instruction"],
                expected_output=payload["expected_output"],
                depends_on=list(payload["depends_on"]),
            ),
            thread_id=payload["thread_id"],
            customer_id=payload["customer_id"],
            conversation_id=payload["conversation_id"],
            user_message=payload["user_message"],
            run_id=str(payload.get("run_id", "")),
            params=dict(payload.get("params", {}) or {}),
            user_profile=dict(payload.get("user_profile", {}) or {}),
            upstream_results={
                dep: DomainOutcome.model_validate(value)
                for dep, value in (payload.get("upstream_results") or {}).items()
            },
        )
        try:
            outcome = domain_runner(context)
        except Exception:  # noqa: BLE001
            outcome = DomainOutcome(
                task_id=payload["task_id"],
                domain=BusinessDomain(payload["domain"]),
                status="failed",
                summary="",
                limitations=[f"domain_runner_failed:{payload['domain']}"],
            )
        return {"task_results": {outcome.task_id: outcome.model_dump(mode="json")}}

    return domain_worker


def make_evaluate_node(
    should_stop: Callable[[], bool] | None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """汇合节点工厂：检查协作式停止与墙钟截止。"""

    def evaluate_node(state: dict[str, Any]) -> dict[str, Any]:
        from finance_agent.orchestrator.graphs.plan_execute_graph import (
            PLAN_CANCELLED_WARNING,
            PLAN_DEADLINE_WARNING,
        )

        if should_stop is not None and should_stop():
            return {"halted": True, "warnings": [PLAN_CANCELLED_WARNING]}
        deadline = state.get("deadline_monotonic")
        if deadline is not None and time.monotonic() >= float(deadline):
            return {"halted": True, "warnings": [PLAN_DEADLINE_WARNING]}
        return {"halted": False}

    return evaluate_node


def route_after_evaluate(state: dict[str, Any]):
    """汇合后的条件路由：继续扇出 / 重规划 / 结束。"""
    from langgraph.graph import END

    from finance_agent.orchestrator.graphs.plan_execute_graph import (
        dispatch_ready_tasks,
        evaluate_plan_results,
    )

    if state.get("halted"):
        return END
    decision = evaluate_plan_results(state)
    if decision.action == "dispatch":
        return dispatch_ready_tasks(state)
    if decision.action == "replan":
        return "replan"
    return END


def make_replan_node(
    planner: Callable[[dict[str, Any], list[BusinessDomain]], Any] | None,
    *,
    replan_limit: int,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """重规划节点工厂；保留已完成 task_id（同 ID 视为已完成，不重复执行）。"""

    def replan_node(state: dict[str, Any]) -> dict[str, Any]:
        used = int(state.get("replans_used", 0) or 0)
        limit = int(state.get("replan_limit", replan_limit) or replan_limit)
        if planner is None or used >= limit:
            return {"warnings": ["replan_unavailable"]}
        domains = [BusinessDomain(value) for value in state.get("domains", [])]
        new_plan = planner(state, domains)
        return {"plan": new_plan.model_dump(mode="json"), "replans_used": used + 1}

    return replan_node


__all__ = [
    "after_plan",
    "make_domain_worker",
    "make_evaluate_node",
    "make_plan_node",
    "make_replan_node",
    "route_after_evaluate",
]
