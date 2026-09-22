"""Supervisor Graph：领域分类、路由与兼容投影（设计 §5、§6.2、§6.5）。

Supervisor Graph 只决定“属于哪个业务领域、是否需要跨领域规划”，并调用注入的
会话/领域/计划执行器。它不承载任何工具实现；取数与计算由各领域子图完成。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy
from typing_extensions import TypedDict

from finance_agent.contracts import RunStatus
from finance_agent.orchestrator.contracts import (
    DEGRADED_RUN_STATUSES,
    DOMAIN_STATUS_TO_RUN_STATUS,
    BusinessDomain,
    DomainOutcome,
    DomainTaskContext,
    ExecutionPlan,
    PlanTask,
    RoutingDecision,
)
# 意图 → 业务领域沿用分类器的注册表（唯一事实源），此处不再硬编码一份：
# 两份映射曾发生漂移（account_query 只在分类器登记、路由表却缺席）。
from finance_agent.orchestrator.intent import _INTENT_TO_DOMAIN
# 节点函数统一收敛在 nodes 包；根图模块只负责装配节点与边。
from finance_agent.orchestrator.nodes.supervisor import (
    classification_error_handler,
    clarify_node,
    compliance_error_handler,
    compliance_node,
    degradation_error_handler,
    make_classify_node,
    make_conversation_node,
    make_plan_node,
    make_single_domain_node,
    route,
)
# 停止原因码在 plan_node 中判定运行状态，必须模块级可见：若只在某个分支内
# 导入，外部注入 plan_runner 时该名字不存在，plan_node 会 NameError。
from finance_agent.orchestrator.plan_execute import PLAN_CANCELLED_WARNING

# casual_chat 在注册表中映射为 None，不属于任何业务领域。

# 领域稳定排序，保证多领域路由结果确定。
# 注意：该元组同时被 ``.index`` 用作排序键，新增领域必须同步加入，否则 ValueError。
_DOMAIN_ORDER = (
    BusinessDomain.STOCK_RESEARCH,
    BusinessDomain.MARKET_INSIGHT,
    BusinessDomain.PRODUCT_RESEARCH,
    BusinessDomain.ACCOUNT_PORTFOLIO,
)

CLASSIFICATION_FAILED_RESPONSE = "暂时无法识别该请求的业务领域，请稍后重试或换一种说法。"
CLARIFICATION_FALLBACK = "请补充更具体的信息，例如要分析的标的、市场范围或产品类型。"
CANCELLED_RESPONSE = "已停止本次生成。"


class SupervisorState(TypedDict, total=False):
    user_message: str
    history: str
    customer_id: str
    conversation_id: str
    thread_id: str
    run_id: str
    routing: dict[str, Any]
    final_response: str
    run_status: str
    warnings: list[str]
    task_results: dict[str, dict[str, Any]]
    domain_outcomes: dict[str, dict[str, Any]]
    compliance: dict[str, Any]
    single_task_id: str
    # 该轮回答是否来自受信来源（FAQ 原文）；为真时合规只审计、不改写。
    trusted_content: bool


def classify_domains(
    message: str,
    context_summary: str = "",
    *,
    classifier: Any,
) -> RoutingDecision:
    """把现有分类器输出映射为三领域路由决策。"""
    classified = classifier.classify_intents(message, context_summary)

    error = classified.get("classification_error") or {}
    if error:
        return RoutingDecision(
            domains=[],
            execution_mode="clarify",
            clarification=CLASSIFICATION_FAILED_RESPONSE,
            error_code=str(error.get("error_code") or "classification_error"),
        )

    intents = classified.get("intents", []) or []
    domains: list[BusinessDomain] = []
    domain_queries: dict[str, str] = {}
    for item in intents:
        domain = _INTENT_TO_DOMAIN.get(str(item.get("intent", "")))
        if domain is None:
            continue
        if domain not in domains:
            domains.append(domain)
        # 记录该领域的子请求：复合请求下每个领域只处理属于自己的那部分，
        # 避免把整句（含其它领域实体）丢给单一领域而解析失败。
        query = str(item.get("query", "")).strip()
        if query and not domain_queries.get(domain.value):
            domain_queries[domain.value] = query
    domains.sort(key=_DOMAIN_ORDER.index)
    uncertain = classified.get("uncertain_intents", []) or []

    if not domains:
        if uncertain:
            return RoutingDecision(
                domains=[],
                execution_mode="clarify",
                clarification=CLARIFICATION_FALLBACK,
            )
        return RoutingDecision(domains=[], execution_mode="conversation")

    # 低置信度意图不进入执行，但**不得静默丢弃**：把被跳过的子请求与所需澄清
    # 作为提示带回，让用户知道哪一部分没执行、需要补充什么。
    dropped_notes: list[str] = []
    for item in uncertain:
        query = str(item.get("query", "")).strip()
        ask = str(item.get("clarification_question", "")).strip()
        if query:
            note = f"「{query}」未执行：{ask}" if ask else f"「{query}」信息不足，请补充更具体的需求。"
        else:
            note = ask or CLARIFICATION_FALLBACK
        if note not in dropped_notes:
            dropped_notes.append(note)

    if len(domains) == 1:
        return RoutingDecision(
            domains=domains, execution_mode="domain_react",
            domain_queries=domain_queries, warnings=dropped_notes,
        )
    return RoutingDecision(
        domains=domains, execution_mode="plan_execute",
        domain_queries=domain_queries, warnings=dropped_notes,
    )


@dataclass
class SupervisorDependencies:
    """Supervisor Graph 的可注入执行依赖；领域/计划执行器可后置接入。"""

    classifier: Any
    conversation_runner: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    domain_runner: Callable[[DomainTaskContext], DomainOutcome] | None = None
    plan_runner: Callable[[dict[str, Any], list[BusinessDomain]], list[DomainOutcome]] | None = None
    planner: Callable[[dict[str, Any], list[BusinessDomain]], ExecutionPlan] | None = None
    replan_limit: int = 2
    extra_warnings: list[str] = field(default_factory=list)
    # 整轮计划的墙钟上限（秒）；<=0 表示不限。由 run_plan_execute 强制。
    plan_deadline_seconds: float = 0.0
    # 协作式停止查询：返回 True 时不再下发新的领域任务，已完成结果保留。
    should_stop: Callable[[], bool] | None = None
    # 受校验运行预算（config.ORCHESTRATION_* 的唯一投影）。None 时各节点回退
    # config 默认；显式传入时计划任务上限与重规划次数从这里取。
    budgets: Any = None


@dataclass
class PlanRunResult:
    """计划执行的完整结果：领域结论 + 降级原因 + 运行状态。

    只回传 ``list[DomainOutcome]`` 会丢掉两个关键信息：任务因超时/停止被跳过时
    这些任务没有 outcome，仅凭结论集合会误判为 completed；以及降级原因
    （如 ``plan_deadline_exceeded``）需要进入 warnings 才可观测。
    """

    outcomes: list[DomainOutcome]
    warnings: list[str] = field(default_factory=list)
    run_status: str = ""
    degraded: bool = False


def _single_task_id(run_id: str, domain: BusinessDomain) -> str:
    return f"single:{run_id}:{domain.value}"


def _single_task(goal: str, instruction: str, domain: BusinessDomain, task_id: str) -> PlanTask:
    return PlanTask(
        task_id=task_id,
        domain=domain,
        goal=goal,
        instruction=instruction,
        expected_output="domain_outcome",
    )


def build_supervisor_graph(dependencies: SupervisorDependencies, *, checkpointer: Any = None):
    """编译 Supervisor Graph；节点只做分类、路由和执行器编排。

    ``checkpointer`` 为 ``None`` 时不持久化（单次调用与测试场景）；生产由
    ``AdvisorSystem`` 注入 PostgresSaver，使运行状态按 ``thread_id`` 落库，
    进程崩溃/重启后可从最近一个 superstep 的 checkpoint 继续，而不是整轮丢弃。
    """

    plan_runner = dependencies.plan_runner
    planner = dependencies.planner
    budgets = dependencies.budgets
    replan_limit = budgets.replans if budgets is not None else dependencies.replan_limit
    plan_task_limit = budgets.plan_tasks if budgets is not None else 0
    if plan_runner is None and dependencies.domain_runner is not None:
        # 未显式提供计划执行器时，直接运行编译后的 Plan-and-Execute 子图。
        # 未提供 Planner 时回退确定性的每领域一任务计划。
        from finance_agent.orchestrator.plan_execute import (
            build_plan_execute_graph,
            deterministic_planner,
        )

        planner = planner or deterministic_planner
        plan_graph = build_plan_execute_graph(
            domain_runner=dependencies.domain_runner,
            planner=planner,
            replan_limit=replan_limit,
            max_seconds=dependencies.plan_deadline_seconds,
            should_stop=dependencies.should_stop,
            task_limit=plan_task_limit,
        )

        def plan_runner(state: dict[str, Any], domains: list[BusinessDomain]):
            result = plan_graph.invoke(
                {
                    "domains": [domain.value for domain in domains],
                    "routing": dict(state.get("routing", {}) or {}),
                    "thread_id": str(state.get("thread_id", "")),
                    "run_id": str(state.get("run_id", "")),
                    "customer_id": str(state.get("customer_id", "")),
                    "conversation_id": str(state.get("conversation_id", "")),
                    "user_message": str(state.get("user_message", "")),
                    "replan_limit": replan_limit,
                }
            )
            return PlanRunResult(
                outcomes=[
                    DomainOutcome.model_validate(value)
                    for value in (result.get("task_results", {}) or {}).values()
                ],
                warnings=list(result.get("warnings", []) or []),
                run_status="",
            )

    classify_node = make_classify_node(dependencies.classifier)
    conversation_node = make_conversation_node(dependencies.conversation_runner)
    single_domain_node = make_single_domain_node(
        dependencies.domain_runner, dependencies.should_stop,
    )
    assembled_plan_node = make_plan_node(plan_runner)

    graph = StateGraph(SupervisorState)
    # 图级默认重试：瞬时的模型/网络故障应当自动重试一次，而不是立刻降级。
    # 领域/计划节点可能提交量化任务，但 QuantGateway 的 submit 以
    # idempotency_key 保证幂等，因此重试不会重复下单。
    graph.set_node_defaults(retry_policy=RetryPolicy(max_attempts=2, initial_interval=0.5))
    graph.add_node("classify", classify_node, error_handler=classification_error_handler)
    graph.add_node("conversation", conversation_node, error_handler=degradation_error_handler)
    graph.add_node("clarify", clarify_node)
    graph.add_node("single_domain", single_domain_node, error_handler=degradation_error_handler)
    graph.add_node("plan", assembled_plan_node, error_handler=degradation_error_handler)
    # 合规出口失败必须 fail-closed：绝不把未经校验的草稿当作结果返回。
    graph.add_node("compliance", compliance_node, error_handler=compliance_error_handler)
    graph.add_edge(START, "classify")
    graph.add_conditional_edges(
        "classify",
        route,
        {
            "conversation": "conversation",
            "clarify": "clarify",
            "single_domain": "single_domain",
            "plan": "plan",
        },
    )
    for node in ("conversation", "clarify", "single_domain", "plan"):
        graph.add_edge(node, "compliance")
    graph.add_edge("compliance", END)
    return graph.compile(checkpointer=checkpointer)


def _status_from_outcome(outcome: DomainOutcome) -> str:
    return DOMAIN_STATUS_TO_RUN_STATUS.get(outcome.status, RunStatus.PARTIAL.value)


def _pending_job_ids(outcomes: dict[str, Any]) -> list[str]:
    """收集 processing 结论中的真实 Celery job_id（去重、稳定排序）。

    兼容两种来源：结论显式携带的 ``pending_jobs``（恢复/新写入路径），
    以及 ``structured_data.pending_jobs``（领域图写回的结构化字段）。
    两者都缺失时不再回退到领域 task_id——回退值对状态端点无意义，
    会让前端拿到查不到的 id。
    """
    job_ids: set[str] = set()
    for value in outcomes.values():
        if not isinstance(value, dict) or value.get("status") != "processing":
            continue
        refs = list(value.get("pending_jobs") or [])
        structured = value.get("structured_data") or {}
        if isinstance(structured, dict):
            refs += list(structured.get("pending_jobs") or [])
        for ref in refs:
            if isinstance(ref, dict) and ref.get("job_id"):
                job_ids.add(str(ref["job_id"]))
    return sorted(job_ids)


def reduce_run_status(
    outcomes: list[DomainOutcome],
    extra_warnings: list[str],
    reported_status: str = "",
) -> str:
    """由领域结论集合与执行器上报归约为本轮运行状态（纯函数）。

    优先级链（高 → 低，修改任一层都会影响前端"停止"与"出错"的区分）：

    1. **结论集合**：全部 completed → completed；全部 failed → failed；其余
       （含空集合、混合、processing）→ partial；
    2. **用户主动停止**：``PLAN_CANCELLED_WARNING`` 出现即覆盖为 cancelled ——
       必须高于执行器上报，否则前端无法区分"停止"与"出错"；
    3. **执行器上报**：上报为降级状态（failed/partial）时覆盖前值，避免"已完成的
       那部分全成功"掩盖被跳过的任务；上报 completed 时不覆盖（保留结论集合判定）；
    4. **warnings 降级**：存在任何告警时，completed 降级为 partial（有告警即不可
       声称完全成功）。
    """
    statuses = {_status_from_outcome(outcome) for outcome in outcomes}
    if statuses == {RunStatus.COMPLETED.value}:
        run_status = RunStatus.COMPLETED.value
    elif statuses == {RunStatus.FAILED.value}:
        run_status = RunStatus.FAILED.value
    else:
        run_status = RunStatus.PARTIAL.value

    if PLAN_CANCELLED_WARNING in extra_warnings:
        run_status = RunStatus.CANCELLED.value
    elif reported_status and reported_status != RunStatus.COMPLETED.value:
        if reported_status in DEGRADED_RUN_STATUSES:
            run_status = reported_status

    if extra_warnings and run_status == RunStatus.COMPLETED.value:
        run_status = RunStatus.PARTIAL.value
    return run_status


def single_domain_task_id(run_id: str, domain: BusinessDomain) -> str:
    """外部（测试/恢复）复用的单领域任务标识。"""
    return _single_task_id(run_id, domain)


# 现有响应键必须保留；V2 只追加 run_status/task_id/pending_task_ids/warnings。
_V2_RESPONSE_KEYS = (
    "response",
    "task_plan",
    "task_dispatch",
    "tasks",
    "task_results",
    "user_profile",
    "stock_data",
    "fundamental_analysis",
    "stock_analysis",
    "technical_analysis",
    "analysis_results",
    "theme_screening",
    "theme_screening_status",
    "theme_candidates",
    "pending_leads",
    "personalization_status",
    "product_analysis",
    "market_insight",
    "compliance_result",
    "conversation_id",
    "run_status",
    "warnings",
    "account",
)


def project_supervisor_state(state: dict[str, Any], *, conversation_id: str = "") -> dict[str, Any]:
    """把 Supervisor Graph 终态投影为兼容现有 /api/chat 的响应字典。

    保留全部既有字段（缺省为空），只追加 run_status/task_id/pending_task_ids/warnings。
    """
    routing = state.get("routing", {}) or {}
    domains = list(routing.get("domains", []) or [])
    outcomes = state.get("domain_outcomes", {}) or {}

    output: dict[str, Any] = {key: None for key in _V2_RESPONSE_KEYS}
    output.update(
        {
            "response": str(state.get("final_response", "") or ""),
            "task_plan": list(domains),
            "task_dispatch": [],
            "tasks": [],
            "task_results": dict(state.get("task_results", {}) or {}),
            "user_profile": {},
            "stock_data": {},
            "fundamental_analysis": {},
            "stock_analysis": {},
            "technical_analysis": {},
            "analysis_results": [],
            "theme_screening": {},
            "theme_screening_status": "",
            "theme_candidates": [],
            "pending_leads": [],
            "personalization_status": "",
            "product_analysis": {},
            "market_insight": {},
            "compliance_result": dict(state.get("compliance", {}) or {}),
            "conversation_id": conversation_id,
            "run_status": str(state.get("run_status", "completed")),
            "warnings": list(state.get("warnings", []) or []),
            "account": {},
            # 待处理异步任务的标识必须是**真实 Celery job_id**：状态端点
            # GET /api/runs/{task_id} 按 job_id（即仓储主键）查询。此前返回领域
            # 任务 id（single:{run_id}:{domain}），端点永远查不到，前端只能轮询到
            # not_found。这里改从 processing 结论的 pending_jobs 收集 job_id。
            "pending_task_ids": _pending_job_ids(outcomes),
        }
    )

    for outcome in outcomes.values():
        if not isinstance(outcome, dict):
            continue
        data = outcome.get("structured_data", {}) or {}
        domain = outcome.get("domain")
        if domain == BusinessDomain.STOCK_RESEARCH.value:
            for key in (
                "stock_data",
                "fundamental_analysis",
                "stock_analysis",
                "technical_analysis",
                "theme_screening",
                "theme_candidates",
                "analysis_results",
                "facts",
                "research_request",
            ):
                if key in data:
                    output[key] = data[key]
            for key in ("theme_screening_status", "personalization_status", "pending_leads"):
                if key in data:
                    output[key] = data[key]
        elif domain == BusinessDomain.MARKET_INSIGHT.value:
            output["market_insight"] = data.get("market_insight", data)
        elif domain == BusinessDomain.PRODUCT_RESEARCH.value:
            nested = data.get("product_analysis")
            output["product_analysis"] = nested if isinstance(nested, dict) else data
        elif domain == BusinessDomain.ACCOUNT_PORTFOLIO.value:
            # 账户领域投影为 {account, positions}；两者都只读。
            output["account"] = {
                "account": data.get("account", {}) or {},
                "positions": data.get("positions", []) or [],
                "mode": data.get("mode", ""),
            }

    # 复合请求的每领域 summary 组成 response（Root 已拼接则保持原值）。
    return output


__all__ = [
    "CANCELLED_RESPONSE",
    "CLASSIFICATION_FAILED_RESPONSE",
    "CLARIFICATION_FALLBACK",
    "PlanRunResult",
    "SupervisorDependencies",
    "SupervisorState",
    "build_supervisor_graph",
    "classify_domains",
    "project_supervisor_state",
    "reduce_run_status",
    "single_domain_task_id",
]
