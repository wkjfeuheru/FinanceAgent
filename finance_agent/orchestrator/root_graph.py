"""Root Graph：领域分类、路由与兼容投影（设计 §5、§6.2、§6.5）。

Root Graph 只决定“属于哪个业务领域、是否需要跨领域规划”，并调用注入的
会话/领域/计划执行器。它不承载任何工具实现；取数与计算由各领域子图完成。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from finance_agent.orchestrator.contracts import (
    BusinessDomain,
    DomainOutcome,
    DomainTaskContext,
    ExecutionPlan,
    PlanTask,
    RoutingDecision,
)

# 现有细粒度意图 → 三个顶层业务领域；casual_chat 不属于任何业务领域。
_INTENT_TO_DOMAIN: dict[str, BusinessDomain | None] = {
    "stock_analysis": BusinessDomain.STOCK_RESEARCH,
    "stock_recommendation": BusinessDomain.STOCK_RESEARCH,
    "market_insight": BusinessDomain.MARKET_INSIGHT,
    "product_analysis": BusinessDomain.PRODUCT_RESEARCH,
    "casual_chat": None,
}

# 领域稳定排序，保证多领域路由结果确定。
_DOMAIN_ORDER = (
    BusinessDomain.STOCK_RESEARCH,
    BusinessDomain.MARKET_INSIGHT,
    BusinessDomain.PRODUCT_RESEARCH,
)

CLASSIFICATION_FAILED_RESPONSE = "暂时无法识别该请求的业务领域，请稍后重试或换一种说法。"
CLARIFICATION_FALLBACK = "请补充更具体的信息，例如要分析的标的、市场范围或产品类型。"


class RootState(TypedDict, total=False):
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
    for item in intents:
        domain = _INTENT_TO_DOMAIN.get(str(item.get("intent", "")))
        if domain is not None and domain not in domains:
            domains.append(domain)
    domains.sort(key=_DOMAIN_ORDER.index)

    if not domains:
        uncertain = classified.get("uncertain_intents", []) or []
        if uncertain:
            return RoutingDecision(
                domains=[],
                execution_mode="clarify",
                clarification=CLARIFICATION_FALLBACK,
            )
        return RoutingDecision(domains=[], execution_mode="conversation")

    if len(domains) == 1:
        return RoutingDecision(domains=domains, execution_mode="domain_react")
    return RoutingDecision(domains=domains, execution_mode="plan_execute")


@dataclass
class RootGraphDependencies:
    """Root Graph 的可注入执行依赖；领域/计划执行器可后置接入。"""

    classifier: Any
    conversation_runner: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    domain_runner: Callable[[DomainTaskContext], DomainOutcome] | None = None
    plan_runner: Callable[[dict[str, Any], list[BusinessDomain]], list[DomainOutcome]] | None = None
    planner: Callable[[dict[str, Any], list[BusinessDomain]], ExecutionPlan] | None = None
    replan_limit: int = 2
    extra_warnings: list[str] = field(default_factory=list)


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


def build_root_graph(dependencies: RootGraphDependencies):
    """编译 Root Graph；节点只做分类、路由和执行器编排。"""

    plan_runner = dependencies.plan_runner
    if plan_runner is None and dependencies.domain_runner is not None and dependencies.planner is not None:
        # 未显式提供计划执行器时，用统一的 Send 调度执行 Planner 产出的计划。
        from finance_agent.orchestrator.plan_execute import run_plan_execute

        def plan_runner(state: dict[str, Any], domains: list[BusinessDomain]):
            plan = dependencies.planner(state, domains)
            result = run_plan_execute(
                domain_runner=dependencies.domain_runner,
                initial_plan=plan,
                planner=dependencies.planner,
                thread_id=str(state.get("thread_id", "")),
                run_id=str(state.get("run_id", "")),
                customer_id=str(state.get("customer_id", "")),
                conversation_id=str(state.get("conversation_id", "")),
                user_message=str(state.get("user_message", "")),
                replan_limit=dependencies.replan_limit,
            )
            return [DomainOutcome.model_validate(value) for value in result["task_results"].values()]

    def classify_node(state: RootState) -> dict[str, Any]:
        routing = classify_domains(
            str(state.get("user_message", "")),
            str(state.get("history", "") or ""),
            classifier=dependencies.classifier,
        )
        return {"routing": routing.model_dump(mode="json")}

    def conversation_node(state: RootState) -> dict[str, Any]:
        if dependencies.conversation_runner is None:
            return {
                "final_response": "会话能力暂不可用，请稍后重试。",
                "run_status": "failed",
                "warnings": ["conversation_runner_unavailable"],
            }
        result = dependencies.conversation_runner(dict(state))
        return {
            "final_response": result.get("final_response", ""),
            "run_status": "completed" if result.get("status") == "success" else "partial",
            "warnings": list(result.get("warnings", []) or []),
        }

    def clarify_node(state: RootState) -> dict[str, Any]:
        routing = state.get("routing", {}) or {}
        if routing.get("error_code"):
            return {
                "final_response": str(routing.get("clarification") or CLASSIFICATION_FAILED_RESPONSE),
                "run_status": "failed",
                "warnings": [f"classification_error:{routing['error_code']}"],
            }
        return {
            "final_response": str(routing.get("clarification") or CLARIFICATION_FALLBACK),
            "run_status": "completed",
        }

    def single_domain_node(state: RootState) -> dict[str, Any]:
        routing = state.get("routing", {}) or {}
        domain = BusinessDomain(routing["domains"][0])
        run_id = str(state.get("run_id", ""))
        task_id = _single_task_id(run_id, domain)
        updates: dict[str, Any] = {"single_task_id": task_id}
        if dependencies.domain_runner is None:
            updates.update(
                {
                    "final_response": "该业务领域能力暂不可用，请稍后重试。",
                    "run_status": "failed",
                    "warnings": [f"domain_runner_unavailable:{domain.value}"],
                }
            )
            return updates

        outcome = dependencies.domain_runner(
            DomainTaskContext(
                task=_single_task(
                    goal=str(state.get("user_message", "")),
                    instruction=str(state.get("user_message", "")),
                    domain=domain,
                    task_id=task_id,
                ),
                thread_id=str(state.get("thread_id", "")),
                customer_id=str(state.get("customer_id", "")),
                conversation_id=str(state.get("conversation_id", "")),
                user_message=str(state.get("user_message", "")),
            )
        )
        return {
            **updates,
            "final_response": outcome.summary,
            "run_status": _status_from_outcome(outcome),
            "domain_outcomes": {task_id: outcome.model_dump(mode="json")},
            "task_results": {task_id: outcome.model_dump(mode="json")},
            "warnings": list(outcome.limitations),
        }

    def plan_node(state: RootState) -> dict[str, Any]:
        routing = state.get("routing", {}) or {}
        domains = [BusinessDomain(value) for value in routing.get("domains", [])]
        if plan_runner is None:
            return {
                "final_response": "跨领域规划能力暂不可用，请拆分为单个领域分别提问。",
                "run_status": "failed",
                "warnings": ["plan_runner_unavailable"],
            }
        outcomes = plan_runner(dict(state), domains)
        responses = [outcome.summary for outcome in outcomes if outcome.summary]
        statuses = {_status_from_outcome(outcome) for outcome in outcomes}
        run_status = "completed" if statuses == {"completed"} else ("failed" if statuses == {"failed"} else "partial")
        return {
            "final_response": "\n\n".join(responses),
            "run_status": run_status,
            "task_results": {outcome.task_id: outcome.model_dump(mode="json") for outcome in outcomes},
            "domain_outcomes": {outcome.task_id: outcome.model_dump(mode="json") for outcome in outcomes},
            "warnings": [limitation for outcome in outcomes for limitation in outcome.limitations],
        }

    def route(state: RootState) -> str:
        routing = state.get("routing", {}) or {}
        mode = routing.get("execution_mode", "conversation")
        if routing.get("error_code"):
            return "clarify"
        if mode == "clarify":
            return "clarify"
        if mode == "domain_react":
            return "single_domain"
        if mode == "plan_execute":
            return "plan"
        return "conversation"

    def compliance_node(state: RootState) -> dict[str, Any]:
        """所有执行模式的成功/部分/降级输出都必须经过合规出口。"""
        from finance_agent.orchestrator.compliance import run_compliance

        outcome_refs: list[dict[str, Any]] = []
        for value in (state.get("task_results", {}) or {}).values():
            if isinstance(value, dict):
                for ref in value.get("evidence", []) or []:
                    if isinstance(ref, dict):
                        outcome_refs.append(
                            {"fact_id": str(ref.get("uri", "")), "value": ref.get("content_hash", "")}
                        )
        result = run_compliance(draft=str(state.get("final_response", "")), evidence=outcome_refs)
        updates: dict[str, Any] = {
            "compliance": result.model_dump(mode="json"),
            "final_response": result.response,
        }
        if result.action == "blocked":
            updates["run_status"] = "failed"
            updates["warnings"] = list(state.get("warnings", []) or []) + ["compliance_blocked"]
        return updates

    graph = StateGraph(RootState)
    graph.add_node("classify", classify_node)
    graph.add_node("conversation", conversation_node)
    graph.add_node("clarify", clarify_node)
    graph.add_node("single_domain", single_domain_node)
    graph.add_node("plan", plan_node)
    graph.add_node("compliance", compliance_node)
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
    return graph.compile()


def _status_from_outcome(outcome: DomainOutcome) -> str:
    mapping = {
        "success": "completed",
        "partial": "partial",
        "processing": "processing",
        "failed": "failed",
    }
    return mapping.get(outcome.status, "partial")


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
)


def project_root_state(state: dict[str, Any], *, conversation_id: str = "") -> dict[str, Any]:
    """把 Root Graph 终态投影为兼容现有 /api/chat 的响应字典。

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
            "pending_task_ids": sorted(
                str(value.get("task_id"))
                for value in outcomes.values()
                if isinstance(value, dict) and value.get("status") == "processing"
            ),
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

    # 复合请求的每领域 summary 组成 response（Root 已拼接则保持原值）。
    return output


__all__ = [
    "CLASSIFICATION_FAILED_RESPONSE",
    "CLARIFICATION_FALLBACK",
    "RootGraphDependencies",
    "RootState",
    "build_root_graph",
    "classify_domains",
    "project_root_state",
    "single_domain_task_id",
]
