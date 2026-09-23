"""跨领域 Plan-and-Execute 与统一 Send 调度（设计 §6.5、§7）。

Planner 只做跨领域分解与依赖；领域内部工具调用不在这一层。计划通过
``validate_execution_plan`` 校验后，由 ``dispatch_ready_tasks`` 统一用 LangGraph
``Send`` 扇出全部就绪任务；股票、市场、产品分支使用同一调度协议，没有领域旁路。
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Annotated, Any, Callable

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from finance_agent.orchestrator.contracts import (
    BusinessDomain,
    DomainOutcome,
    DomainTaskContext,
    ExecutionPlan,
    NodeError,
    PlanDecision,
    PlanTask,
)
from finance_agent.orchestrator.nodes.plan_execute import (
    after_plan,
    make_domain_worker,    make_evaluate_node,
    make_replan_node,
    route_after_evaluate,
)
from finance_agent.orchestrator.state import dedupe_concat, merge_dict

def _plan_task_limit() -> int:
    from finance_agent import config

    return config.ORCHESTRATION_PLAN_TASKS


def _replan_limit() -> int:
    from finance_agent import config

    return config.ORCHESTRATION_REPLANS


# 计划任务数与重规划次数的唯一数值源是 config 的 ORCHESTRATION_* 变量；
# 此处只保留别名供既有调用方与校验提示使用，不再独立定义数值。
PLAN_TASK_LIMIT = _plan_task_limit()
REPLAN_LIMIT = _replan_limit()
# 降级原因码：必须可被上层识别并汇入 warnings（不是仅供日志）。
PLAN_DEADLINE_WARNING = "plan_deadline_exceeded"
PLAN_CANCELLED_WARNING = "plan_cancelled_by_user"


class PlanExecuteState(TypedDict, total=False):
    """Plan-and-Execute 子图私有状态（Send 并发写 task_results/warnings）。"""

    plan: dict[str, Any]
    task_results: Annotated[dict[str, dict[str, Any]], merge_dict]
    replans_used: int
    replan_limit: int
    thread_id: str
    run_id: str
    customer_id: str
    conversation_id: str
    user_message: str
    plan_error: dict[str, Any]
    warnings: Annotated[list[str], dedupe_concat]
    domains: list[str]
    # Supervisor Graph 已按领域切分 query；Planner 需要保留它，不能退回整句用户请求。
    routing: dict[str, Any]
    deadline_monotonic: float
    halted: bool
    # 根图抽取到的参数（含弹窗补填）与用户画像卡：随 Send payload 传给各领域任务。
    extracted_params: dict[str, Any]
    user_profile: dict[str, Any]


class PlanValidationResult(BaseModel):
    """计划校验结果；无效时携带结构化 NodeError。"""

    valid: bool
    plan: ExecutionPlan | None = None
    error: NodeError | None = None


def _node_error(code: str, message: str) -> NodeError:
    return NodeError(
        code=code,
        category="validation",
        retryable=False,
        safe_message=message,
        internal_ref=code,
    )


def _as_plan(plan: ExecutionPlan | dict[str, Any] | None) -> ExecutionPlan | None:
    if plan is None:
        return None
    if isinstance(plan, ExecutionPlan):
        return plan
    try:
        return ExecutionPlan.model_validate(plan)
    except Exception:
        return None


def _has_cycle(tasks: list[PlanTask]) -> bool:
    graph: dict[str, list[str]] = {task.task_id: list(task.depends_on) for task in tasks}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visited:
            return False
        if node in visiting:
            return True
        visiting.add(node)
        for dep in graph.get(node, []):
            if dep in graph and visit(dep):
                return True
        visiting.discard(node)
        visited.add(node)
        return False

    return any(visit(node) for node in graph)


def validate_execution_plan(
    plan: ExecutionPlan | dict[str, Any] | None,
    *,
    task_limit: int = 0,
) -> PlanValidationResult:
    """校验任务数量、唯一性、领域、依赖与期望输出。

    ``task_limit`` 为 0 时取 ``PLAN_TASK_LIMIT``（由配置驱动），显式传入时
    可按 profile 收紧但不得超过全局上限。
    """
    limit = task_limit if task_limit > 0 else PLAN_TASK_LIMIT
    parsed = _as_plan(plan)
    if parsed is None:
        return PlanValidationResult(
            valid=False, error=_node_error("plan_invalid", "计划格式不正确。")
        )
    if not parsed.tasks:
        return PlanValidationResult(
            valid=False, error=_node_error("plan_empty", "计划不包含任何任务。")
        )
    if len(parsed.tasks) > limit:
        return PlanValidationResult(
            valid=False,
            error=_node_error("plan_task_limit", f"计划任务数不得超过 {limit}。"),
        )

    ids = [task.task_id for task in parsed.tasks]
    if len(ids) != len(set(ids)):
        return PlanValidationResult(
            valid=False, error=_node_error("plan_duplicate_task_id", "计划任务 ID 必须唯一。")
        )

    valid_ids = set(ids)
    allowed_domains = {domain.value for domain in BusinessDomain}
    for task in parsed.tasks:
        if task.domain.value not in allowed_domains:
            return PlanValidationResult(
                valid=False,
                error=_node_error("plan_domain_not_allowed", "计划包含不允许的业务领域。"),
            )
        if not str(task.expected_output or "").strip():
            return PlanValidationResult(
                valid=False,
                error=_node_error("plan_missing_expected_output", "每个任务必须声明期望输出。"),
            )
        if task.task_id in task.depends_on:
            return PlanValidationResult(
                valid=False, error=_node_error("plan_dependency_cycle", "任务不能依赖自身。")
            )
        for dep in task.depends_on:
            if dep not in valid_ids:
                return PlanValidationResult(
                    valid=False,
                    error=_node_error("plan_unknown_dependency", "任务依赖了不存在的任务。"),
                )

    if _has_cycle(parsed.tasks):
        return PlanValidationResult(
            valid=False, error=_node_error("plan_dependency_cycle", "计划依赖存在环。")
        )
    return PlanValidationResult(valid=True, plan=parsed)


def _completed(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return dict(state.get("task_results", {}) or {})


def _failed_ids(completed: dict[str, dict[str, Any]]) -> set[str]:
    return {
        task_id
        for task_id, outcome in completed.items()
        if isinstance(outcome, dict) and outcome.get("status") == "failed"
    }


def _plan_of(state: dict[str, Any]) -> ExecutionPlan | None:
    return _as_plan(state.get("plan"))


def _domain_params(state: dict[str, Any], domain: BusinessDomain) -> dict[str, Any]:
    """取该领域抽取到的参数（``extracted_params.values[domain]``）。

    本模块不能导入 supervisor_graph（后者反向依赖本模块的 PLAN_CANCELLED_WARNING），
    因此这里就地解析同一份状态结构。
    """
    extracted = state.get("extracted_params", {}) or {}
    values = extracted.get("values") if isinstance(extracted, dict) else {}
    scoped = (values or {}).get(domain.value) if isinstance(values, dict) else {}
    return dict(scoped) if isinstance(scoped, dict) else {}


def dispatch_ready_tasks(state: dict[str, Any]) -> list[Send]:
    """返回全部就绪任务的 Send；这是唯一构造 Send 的位置。

    就绪条件：任务未完成、全部依赖已完成且无依赖失败。依赖失败的任务阻塞，
    无依赖任务继续。
    """
    plan = _plan_of(state)
    if plan is None:
        return []
    completed = _completed(state)
    failed = _failed_ids(completed)

    sends: list[Send] = []
    for task in plan.tasks:
        if task.task_id in completed:
            continue
        if any(dep in failed for dep in task.depends_on):
            continue
        if any(dep not in completed for dep in task.depends_on):
            continue
        sends.append(
            Send(
                "domain_worker",
                {
                    "task_id": task.task_id,
                    "domain": task.domain.value,
                    "goal": task.goal,
                    "instruction": task.instruction,
                    "expected_output": task.expected_output,
                    "depends_on": list(task.depends_on),
                    "upstream_results": {
                        dep: completed[dep] for dep in task.depends_on if dep in completed
                    },
                    "thread_id": str(state.get("thread_id", "")),
                    "run_id": str(state.get("run_id", "")),
                    "customer_id": str(state.get("customer_id", "")),
                    "conversation_id": str(state.get("conversation_id", "")),
                    "user_message": str(state.get("user_message", "")),
                    # 该领域抽取到的参数与用户画像卡：随 Send payload 下发给
                    # domain_worker，使复合请求与单领域请求获得同样的参数。
                    "params": _domain_params(state, task.domain),
                    "user_profile": dict(state.get("user_profile", {}) or {}),
                },
            )
        )
    return sends


def evaluate_plan_results(state: dict[str, Any]) -> PlanDecision:
    """根据已完成结果决定继续扇出、重新规划或结束。"""
    plan = _plan_of(state)
    if plan is None:
        return PlanDecision(action="finish")

    completed = _completed(state)
    remaining = [task for task in plan.tasks if task.task_id not in completed]
    if not remaining:
        return PlanDecision(action="finish", plan=plan)

    if dispatch_ready_tasks(state):
        return PlanDecision(action="dispatch", plan=plan)

    # 仍有任务但无就绪项：依赖失败或阻塞。还有重规划预算则请求重规划。
    replans_used = int(state.get("replans_used", 0) or 0)
    replan_limit = int(state.get("replan_limit", REPLAN_LIMIT) or REPLAN_LIMIT)
    if replans_used < replan_limit:
        return PlanDecision(action="replan")
    return PlanDecision(action="finish", plan=plan)


def _outcome_status(outcomes: list[DomainOutcome]) -> str:
    if not outcomes:
        return "failed"
    statuses = {outcome.status for outcome in outcomes}
    if statuses == {"success"}:
        return "completed"
    if statuses == {"failed"}:
        return "failed"
    if "processing" in statuses:
        return "processing"
    return "partial"


def run_plan_execute(
    *,
    domain_runner: Callable[[DomainTaskContext], DomainOutcome],
    initial_plan: ExecutionPlan,
    thread_id: str,
    run_id: str,
    customer_id: str,
    conversation_id: str,
    user_message: str,
    planner: Callable[[dict[str, Any], list[BusinessDomain]], ExecutionPlan] | None = None,
    replan_limit: int = REPLAN_LIMIT,
    max_seconds: float = 0.0,
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """执行一个计划：Send 扇出就绪任务、合并结果、必要时重规划。

    ``max_seconds`` 是整轮计划的墙钟上限（<=0 表示不限）。重规划计数只能约束
    "规划了几轮"，管不住"某一轮里的领域执行挂了多久"；没有墙钟上限时，一个卡住的
    领域子图会让整轮请求一直不返回。超限时保留已完成结果并以 partial 收尾。
    ``should_stop`` 提供协作式停止：在每个任务下发前检查，用户请求停止后不再启动
    新的领域执行（已完成的专家结果按设计保留）。
    """
    deadline = time.monotonic() + max_seconds if max_seconds > 0 else None
    completed: dict[str, dict[str, Any]] = {}
    replans_used = 0
    plan = initial_plan
    warnings: list[str] = []

    def _budget_exhausted() -> bool:
        return deadline is not None and time.monotonic() >= deadline

    while True:
        if _budget_exhausted():
            warnings.append(PLAN_DEADLINE_WARNING)
            break
        validation = validate_execution_plan(plan)
        if not validation.valid:
            return {
                "plan_error": validation.error.model_dump(mode="json") if validation.error else {},
                "task_results": completed,
                "warnings": warnings
                + ([f"plan_invalid:{validation.error.code}"] if validation.error else []),
                "run_status": "failed",
            }
        plan = validation.plan

        # 执行全部就绪任务。
        state = {
            "plan": plan.model_dump(mode="json"),
            "task_results": completed,
            "thread_id": thread_id,
            "run_id": run_id,
            "customer_id": customer_id,
            "conversation_id": conversation_id,
            "user_message": user_message,
            "replans_used": replans_used,
            "replan_limit": replan_limit,
        }
        sends = dispatch_ready_tasks(state)
        for send in sends:
            if should_stop is not None and should_stop():
                warnings.append(PLAN_CANCELLED_WARNING)
                break
            if _budget_exhausted():
                warnings.append(PLAN_DEADLINE_WARNING)
                break
            payload = send.arg
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
                upstream_results={
                    dep: DomainOutcome.model_validate(value)
                    for dep, value in (payload.get("upstream_results") or {}).items()
                },
            )
            try:
                outcome = domain_runner(context)
            except Exception:  # noqa: BLE001 - 单任务失败不阻断计划
                outcome = DomainOutcome(
                    task_id=payload["task_id"],
                    domain=BusinessDomain(payload["domain"]),
                    status="failed",
                    summary="",
                    limitations=[f"domain_runner_failed:{payload['domain']}"],
                )
            completed[outcome.task_id] = outcome.model_dump(mode="json")

        if PLAN_CANCELLED_WARNING in warnings or PLAN_DEADLINE_WARNING in warnings:
            break

        decision = evaluate_plan_results(
            {**state, "task_results": completed}
        )
        if decision.action == "finish":
            break
        if decision.action == "dispatch":
            continue
        # replan
        replans_used += 1
        if planner is None:
            warnings.append("replan_unavailable")
            break
        new_plan = planner({**state, "task_results": completed}, [task.domain for task in plan.tasks])
        # 保留已完成任务（同 ID 视为已完成，不重复执行）。
        plan = new_plan

    outcomes = [DomainOutcome.model_validate(value) for value in completed.values()]
    summaries = [outcome.summary for outcome in outcomes if outcome.summary]
    # 降级原因（超时/停止/重规划不可用）单独返回：调用方还要把每个 outcome 的
    # limitations 也并入 warnings，两者混在一起会导致同一条原因被重复记录。
    degradation = list(dict.fromkeys(warnings))
    return {
        "task_results": completed,
        "outcomes": outcomes,
        "final_response": "\n\n".join(summaries),
        "warnings": degradation + [item for outcome in outcomes for item in outcome.limitations],
        "degradation_warnings": degradation,
        "run_status": _outcome_status(outcomes),
    }


def deterministic_planner(
    state: dict[str, Any], domains: list[BusinessDomain],
) -> ExecutionPlan:
    """确定性回退计划：每个业务领域一个任务（使用该领域的子请求，若有）。"""
    message = str(state.get("user_message", ""))
    queries = (state.get("routing") or {}).get("domain_queries") or {}
    seen: set[str] = set()
    tasks: list[PlanTask] = []
    for domain in domains:
        if domain in seen:
            continue
        seen.add(domain)
        scoped = str(queries.get(domain.value) or "").strip() or message
        tasks.append(
            PlanTask(
                task_id=f"plan:{domain.value}",
                domain=domain,
                goal=scoped,
                instruction=scoped,
                expected_output="domain_outcome",
            )
        )
    return ExecutionPlan(tasks=tasks)


_PLANNER_PROMPT = """你是投研编排规划器。用户请求同时涉及以下业务领域：{domains}。

本系统的每个业务领域由一条**确定性的单次流水线**承载，因此规划只做**领域级分解**：
每个业务领域恰好一个任务，不拆分领域内部步骤，不增加重复任务。

只输出 JSON，形如：
{{"tasks": [{{"task_id": "t1", "domain": "stock_research", "goal": "…",
  "instruction": "…", "depends_on": [], "expected_output": "domain_outcome"}}]}}

硬约束：
- domain 只能取 {domains} 之一，且**每个领域最多出现一次**；
- 任务数不超过 {limit}，通常等于业务领域个数；
- task_id 唯一且非空；
- depends_on 只能引用本计划内已出现的 task_id；
- 每个任务必须有非空 expected_output。
用户请求：{message}"""


def _normalize_plan(
    plan: ExecutionPlan,
    domains: list[BusinessDomain],
    message: str,
    domain_queries: dict[str, str] | None = None,
) -> ExecutionPlan | None:
    """把规划结果规范为「每个业务领域恰好一个任务」，并保留该领域的子请求。

    LLM 可能把请求拆成领域内部的多个子任务（本架构下等于重复执行同一条
    确定性流水线）。这里按领域去重；每个任务的 goal/instruction 使用该领域
    自己的子请求（来自分类器 per-intent query），无子请求时回退整句消息。
    """
    wanted = list(dict.fromkeys(domains))
    queries = domain_queries or {}
    by_domain: dict[BusinessDomain, PlanTask] = {}
    for task in plan.tasks:
        by_domain.setdefault(task.domain, task)

    if set(by_domain) != set(wanted):
        return None

    tasks: list[PlanTask] = []
    for domain in wanted:
        source = by_domain[domain]
        scoped = str(queries.get(domain.value) or "").strip() or message
        tasks.append(
            PlanTask(
                task_id=f"plan:{domain.value}",
                domain=domain,
                goal=scoped,
                instruction=scoped,
                depends_on=[],
                expected_output=source.expected_output or "domain_outcome",
            )
        )
    return ExecutionPlan(tasks=tasks)


def build_llm_planner(model: Any, *, fallback: bool = True):
    """把 chat model 适配为 planner；解析或校验失败时回退确定性计划。"""
    from finance_agent.orchestrator.react import build_chat_model_callable

    call = build_chat_model_callable(model, require_json=True)

    def planner(state: dict[str, Any], domains: list[BusinessDomain]) -> ExecutionPlan:
        message = str(state.get("user_message", ""))
        domain_queries = (state.get("routing") or {}).get("domain_queries") or {}
        domain_values = [domain.value for domain in domains]
        prompt = _PLANNER_PROMPT.format(
            domains="、".join(domain_values),
            limit=PLAN_TASK_LIMIT,
            message=message,
        )
        try:
            raw = call([{"role": "system", "content": prompt}])
            payload = json.loads(raw) if isinstance(raw, str) else raw
            plan = ExecutionPlan.model_validate(payload)
            if validate_execution_plan(plan).valid:
                normalized = _normalize_plan(plan, domains, message, domain_queries)
                if normalized is not None:
                    return normalized
        except Exception:  # noqa: BLE001 - 规划失败回退确定性计划
            pass
        if fallback:
            return deterministic_planner(state, domains)
        raise

    return planner


def build_plan_execute_graph(
    *,
    domain_runner: Callable[[DomainTaskContext], DomainOutcome],
    planner: Callable[[dict[str, Any], list[BusinessDomain]], ExecutionPlan] | None = None,
    replan_limit: int = REPLAN_LIMIT,
    max_seconds: float = 0.0,
    should_stop: Callable[[], bool] | None = None,
    task_limit: int = 0,
):
    """编译 Plan-and-Execute 子图（Send 扇出 + 合并 + 可选重规划）。

    ``max_seconds`` 和 ``should_stop`` 在每次任务调度前检查。已发出的 Send
    不可抢占，但到达预算或收到停止请求后不会再下发新的领域任务。
    ``task_limit`` 为 0 时沿用 ``PLAN_TASK_LIMIT``（由配置驱动）。
    """
    from finance_agent.orchestrator.nodes.plan_execute import make_plan_node

    plan_node = make_plan_node(
        planner,
        max_seconds=max_seconds,
        task_limit=task_limit,
    )
    domain_worker = make_domain_worker(domain_runner)
    evaluate_node = make_evaluate_node(should_stop)
    replan_node = make_replan_node(planner, replan_limit=replan_limit)

    graph = StateGraph(PlanExecuteState)
    graph.add_node("plan", plan_node)
    graph.add_node("domain_worker", domain_worker)
    graph.add_node("evaluate", evaluate_node)
    graph.add_node("replan", replan_node)
    graph.add_edge(START, "plan")
    graph.add_conditional_edges("plan", after_plan, {"finish": END, "evaluate": "evaluate"})
    graph.add_conditional_edges(
        "evaluate", route_after_evaluate, ["domain_worker", "replan", END]
    )
    graph.add_edge("domain_worker", "evaluate")
    graph.add_edge("replan", "evaluate")
    return graph.compile()


__all__ = [
    "PLAN_TASK_LIMIT",
    "REPLAN_LIMIT",
    "PlanValidationResult",
    "build_plan_execute_graph",
    "deterministic_planner",
    "dispatch_ready_tasks",
    "evaluate_plan_results",
    "run_plan_execute",
    "validate_execution_plan",
]
