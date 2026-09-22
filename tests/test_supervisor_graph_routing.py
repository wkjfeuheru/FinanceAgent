"""Root Graph 领域路由：三领域映射、执行模式与显式失败。"""

from __future__ import annotations

import pytest

from finance_agent.orchestrator.contracts import BusinessDomain, DomainOutcome
from finance_agent.orchestrator.plan_execute import PLAN_CANCELLED_WARNING
from finance_agent.orchestrator.supervisor_graph import (
    CLASSIFICATION_FAILED_RESPONSE,
    SupervisorDependencies,
    build_supervisor_graph,
    classify_domains,
    reduce_run_status,
)


class _FakeClassifier:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def classify_intents(self, message: str, context_summary: str = "") -> dict:
        return self._payload


def _payload(intents: list[str], *, error: dict | None = None, uncertain: list | None = None) -> dict:
    return {
        "intents": [{"intent": intent, "query": intent, "confidence": 0.99} for intent in intents],
        "uncertain_intents": uncertain or [],
        "finance_related": any(intent != "casual_chat" for intent in intents),
        "intent_source": "deepseek",
        "classification_error": error or {},
    }


@pytest.mark.parametrize(
    ("message", "intents", "domains", "mode"),
    [
        ("你好", ["casual_chat"], [], "conversation"),
        ("分析贵州茅台", ["stock_analysis"], ["stock_research"], "domain_react"),
        ("推荐一些股票", ["stock_recommendation"], ["stock_research"], "domain_react"),
        ("市场情绪怎么样", ["market_insight"], ["market_insight"], "domain_react"),
        ("市场情绪和基金产品怎么搭配", ["market_insight", "product_analysis"],
         ["market_insight", "product_research"], "plan_execute"),
    ],
)
def test_root_routes_by_domain_count(message, intents, domains, mode):
    decision = classify_domains(message, classifier=_FakeClassifier(_payload(intents)))

    assert [domain.value for domain in decision.domains] == domains
    assert decision.execution_mode == mode
    assert decision.error_code == ""


def test_classification_error_routes_to_explicit_clarify_not_conversation():
    decision = classify_domains(
        "随便说点什么",
        classifier=_FakeClassifier(_payload([], error={"error_code": "intent_unavailable"})),
    )

    assert decision.execution_mode == "clarify"
    assert decision.error_code == "intent_unavailable"
    assert decision.domains == []


def test_low_confidence_uncertainty_routes_to_clarify():
    decision = classify_domains(
        "那个东西怎么样",
        classifier=_FakeClassifier(
            _payload([], uncertain=[{"intent": "stock_analysis", "confidence": 0.4, "query": "那个"}])
        ),
    )

    assert decision.execution_mode == "clarify"
    assert decision.error_code == ""


def test_root_graph_creates_deterministic_single_domain_task_id():
    captured = {}

    def domain_runner(context):
        captured["task_id"] = context.task.task_id
        from finance_agent.orchestrator.contracts import DomainOutcome

        return DomainOutcome(
            task_id=context.task.task_id,
            domain=context.task.domain,
            status="success",
            summary="已完成分析。",
        )

    graph = build_supervisor_graph(
        SupervisorDependencies(
            classifier=_FakeClassifier(_payload(["stock_analysis"])),
            domain_runner=domain_runner,
        )
    )
    result = graph.invoke({"user_message": "分析贵州茅台", "run_id": "run-1", "customer_id": "CUST1"})

    assert captured["task_id"] == "single:run-1:stock_research"
    assert result["single_task_id"] == "single:run-1:stock_research"
    assert result["run_status"] == "completed"


def test_root_graph_classification_failure_is_not_silently_treated_as_chat():
    graph = build_supervisor_graph(
        SupervisorDependencies(
            classifier=_FakeClassifier(_payload([], error={"error_code": "intent_unavailable"})),
            conversation_runner=lambda state: {"final_response": "不应被调用", "status": "success"},
        )
    )
    result = graph.invoke({"user_message": "随便", "run_id": "run-1"})

    assert result["run_status"] == "failed"
    assert result["final_response"] == CLASSIFICATION_FAILED_RESPONSE
    assert "classification_error:intent_unavailable" in result["warnings"]


def test_root_graph_conversation_mode_delegates_to_conversation_runner():
    graph = build_supervisor_graph(
        SupervisorDependencies(
            classifier=_FakeClassifier(_payload(["casual_chat"])),
            conversation_runner=lambda state: {"final_response": "你好，我是投顾助手。", "status": "success"},
        )
    )
    result = graph.invoke({"user_message": "你好", "run_id": "run-1"})

    assert result["final_response"] == "你好，我是投顾助手。"
    assert result["run_status"] == "completed"


def test_missing_domain_runner_fails_explicitly_instead_of_silent_success():
    graph = build_supervisor_graph(SupervisorDependencies(classifier=_FakeClassifier(_payload(["stock_analysis"]))))
    result = graph.invoke({"user_message": "分析贵州茅台", "run_id": "run-1", "customer_id": "CUST1"})

    assert result["run_status"] == "failed"
    assert "domain_runner_unavailable:stock_research" in result["warnings"]


def test_composite_routing_carries_per_domain_sub_requests():
    """复合请求必须为每个领域保留其子请求，避免整句下发给单一领域。"""
    payload = {
        "intents": [
            {"intent": "stock_analysis", "query": "分析贵州茅台", "confidence": 0.99},
            {"intent": "product_analysis", "query": "比较合适的基金产品", "confidence": 0.99},
        ],
        "uncertain_intents": [],
        "finance_related": True,
        "intent_source": "deepseek",
        "classification_error": {},
    }
    decision = classify_domains("分析贵州茅台并比较合适的基金产品", classifier=_FakeClassifier(payload))

    assert decision.execution_mode == "plan_execute"
    assert decision.domain_queries["stock_research"] == "分析贵州茅台"
    assert decision.domain_queries["product_research"] == "比较合适的基金产品"


def test_single_domain_routing_uses_scoped_query_for_task():
    """单领域直达时，任务 goal 使用该领域子请求而非整句。"""
    payload = {
        "intents": [
            {"intent": "stock_analysis", "query": "分析600519", "confidence": 0.99},
            {"intent": "casual_chat", "query": "随便聊聊", "confidence": 0.99},
        ],
        "uncertain_intents": [],
        "finance_related": True,
        "intent_source": "deepseek",
        "classification_error": {},
    }
    captured = {}

    def domain_runner(context):
        captured["goal"] = context.task.goal
        from finance_agent.orchestrator.contracts import DomainOutcome

        return DomainOutcome(
            task_id=context.task.task_id, domain=context.task.domain,
            status="success", summary="ok",
        )

    graph = build_supervisor_graph(
        SupervisorDependencies(classifier=_FakeClassifier(payload), domain_runner=domain_runner)
    )
    graph.invoke({"user_message": "分析600519，另外随便聊聊", "run_id": "run-1"})

    assert captured["goal"] == "分析600519"


def test_deterministic_plan_uses_scoped_domain_queries():
    from finance_agent.orchestrator.plan_execute import deterministic_planner

    plan = deterministic_planner(
        {
            "user_message": "分析贵州茅台并比较合适的基金产品",
            "routing": {
                "domain_queries": {
                    "stock_research": "分析贵州茅台",
                    "product_research": "比较合适的基金产品",
                }
            },
        },
        [BusinessDomain.STOCK_RESEARCH, BusinessDomain.PRODUCT_RESEARCH],
    )

    goals = {t.domain.value: t.goal for t in plan.tasks}
    assert goals["stock_research"] == "分析贵州茅台"
    assert goals["product_research"] == "比较合适的基金产品"


def test_default_plan_branch_invokes_compiled_langgraph_subgraph(monkeypatch):
    """复合请求必须由已编译的 Plan-and-Execute 图执行，而非顺序 while 循环。"""
    from finance_agent.orchestrator.contracts import DomainOutcome
    import finance_agent.orchestrator.plan_execute as plan_execute

    captured: dict = {}

    class _CompiledPlanGraph:
        def invoke(self, state):
            captured["state"] = state
            return {
                "task_results": {
                    "plan:market_insight": DomainOutcome(
                        task_id="plan:market_insight",
                        domain=BusinessDomain.MARKET_INSIGHT,
                        status="success",
                        summary="市场结论。",
                    ).model_dump(mode="json"),
                    "plan:product_research": DomainOutcome(
                        task_id="plan:product_research",
                        domain=BusinessDomain.PRODUCT_RESEARCH,
                        status="success",
                        summary="产品结论。",
                    ).model_dump(mode="json"),
                },
                "warnings": [],
            }

    def build_compiled_plan_graph(**kwargs):
        captured["dependencies"] = kwargs
        return _CompiledPlanGraph()

    monkeypatch.setattr(plan_execute, "build_plan_execute_graph", build_compiled_plan_graph)
    graph = build_supervisor_graph(
        SupervisorDependencies(
            classifier=_FakeClassifier(_payload(["market_insight", "product_analysis"])),
            domain_runner=lambda context: (_ for _ in ()).throw(AssertionError("不应直接调用领域执行器")),
        )
    )

    result = graph.invoke(
        {
            "user_message": "市场情绪和基金产品怎么搭配",
            "run_id": "run-1",
            "customer_id": "CUST1",
            "conversation_id": "conv-1",
            "thread_id": "v1:CUST1:conv-1",
        }
    )

    assert captured["dependencies"]["domain_runner"] is not None
    assert captured["state"]["domains"] == ["market_insight", "product_research"]
    assert captured["state"]["thread_id"] == "v1:CUST1:conv-1"
    assert result["run_status"] == "completed"


def test_dropped_low_confidence_intent_is_surfaced_not_silent():
    """有领域可执行、但另有低置信度意图被跳过时，必须向用户说明缺什么。"""
    payload = {
        "intents": [{"intent": "stock_analysis", "query": "分析贵州茅台", "confidence": 0.95}],
        "uncertain_intents": [{
            "intent": "product_analysis", "query": "比较合适的基金产品", "confidence": 0.85,
            "clarification_question": "请补充具体基金名称",
        }],
        "finance_related": True,
        "intent_source": "deepseek",
        "classification_error": {},
    }
    captured = {}

    def domain_runner(context):
        from finance_agent.orchestrator.contracts import DomainOutcome

        return DomainOutcome(
            task_id=context.task.task_id, domain=context.task.domain,
            status="success", summary="贵州茅台分析完成。",
        )

    graph = build_supervisor_graph(
        SupervisorDependencies(classifier=_FakeClassifier(payload), domain_runner=domain_runner)
    )
    result = graph.invoke({"user_message": "分析贵州茅台并比较合适的基金产品", "run_id": "run-1"})

    # 已执行部分正常返回
    assert "贵州茅台分析完成。" in result["final_response"]
    # 未执行部分必须显式说明，不能静默丢弃
    assert "比较合适的基金产品" in result["final_response"]
    assert any(w.startswith("clarification_needed:") for w in result["warnings"])


def test_fully_covered_request_has_no_clarification_note():
    payload = {
        "intents": [{"intent": "stock_analysis", "query": "分析600519", "confidence": 0.95}],
        "uncertain_intents": [],
        "finance_related": True, "intent_source": "deepseek", "classification_error": {},
    }

    def domain_runner(context):
        from finance_agent.orchestrator.contracts import DomainOutcome

        return DomainOutcome(
            task_id=context.task.task_id, domain=context.task.domain,
            status="success", summary="分析完成。",
        )

    graph = build_supervisor_graph(
        SupervisorDependencies(classifier=_FakeClassifier(payload), domain_runner=domain_runner)
    )
    result = graph.invoke({"user_message": "分析600519", "run_id": "run-1"})

    assert "补充说明" not in result["final_response"]
    assert result["warnings"] == []


def test_intent_domain_registry_covers_every_intent_including_account_query():
    """意图→领域映射必须与意图注册表同源同覆盖，防止未来新增意图再次漂移。"""
    from finance_agent.contracts import IntentKind
    from finance_agent.orchestrator import intent as intent_module
    from finance_agent.orchestrator import supervisor_graph as supervisor_graph_module

    # 三张表键集完全一致：领域归属、执行模式、意图顺序都覆盖同一批意图
    assert set(intent_module._INTENT_TO_DOMAIN) == set(intent_module._INTENTS)
    assert set(intent_module._EXECUTION_MODES) == set(intent_module._INTENTS)
    # Supervisor Graph 直接复用注册表对象，不再各自硬编码一份
    assert supervisor_graph_module._INTENT_TO_DOMAIN is intent_module._INTENT_TO_DOMAIN
    # 契约枚举与注册表同源（ExpertResult 的 intent 推导依赖该枚举）
    assert {kind.value for kind in IntentKind} == set(intent_module._INTENTS)
    # 验收点：account_query 出现在所有派生结果中
    assert intent_module._INTENT_TO_DOMAIN["account_query"] is BusinessDomain.ACCOUNT_PORTFOLIO


def test_account_query_intent_routes_to_account_portfolio_domain():
    """account_query 必须真正路由到账户领域，而不是被静默丢弃。"""
    decision = classify_domains(
        "我的持仓怎么样",
        classifier=_FakeClassifier(_payload(["account_query"])),
    )

    assert [domain.value for domain in decision.domains] == ["account_portfolio"]
    assert decision.execution_mode == "domain_react"


def _plan_outcome(task_id: str, status: str) -> DomainOutcome:
    return DomainOutcome(
        task_id=task_id, domain=BusinessDomain.STOCK_RESEARCH, status=status, summary="结论。",
    )


@pytest.mark.parametrize(
    ("statuses", "warnings", "reported", "expected"),
    [
        # 1) 结论集合判定
        (["success"], [], "", "completed"),
        (["success", "success"], [], "", "completed"),
        (["failed", "failed"], [], "", "failed"),
        (["success", "failed"], [], "", "partial"),
        (["success", "processing"], [], "", "partial"),
        ([], [], "", "partial"),
        # 2) 用户主动停止：覆盖集合判定，且优先级高于执行器上报
        (["success"], [PLAN_CANCELLED_WARNING], "", "cancelled"),
        (["failed", "failed"], [PLAN_CANCELLED_WARNING], "", "cancelled"),
        (["success"], [PLAN_CANCELLED_WARNING], "failed", "cancelled"),
        # 3) 执行器上报的降级状态覆盖前值；上报 completed 或未知值不覆盖
        (["success"], [], "failed", "failed"),
        (["success"], [], "partial", "partial"),
        (["failed", "failed"], [], "partial", "partial"),
        (["success"], [], "completed", "completed"),
        (["success"], [], "unknown", "completed"),
        # 4) 有告警时 completed 降级为 partial；非 completed 不受影响
        (["success"], ["plan_deadline_exceeded"], "", "partial"),
        (["success"], ["plan_deadline_exceeded"], "completed", "partial"),
        (["failed", "failed"], ["plan_deadline_exceeded"], "", "failed"),
    ],
)
def test_reduce_run_status_priority_chain(statuses, warnings, reported, expected):
    """运行状态归约的优先级链：集合判定 < 上报降级 < 用户停止，另有告警降级。"""
    outcomes = [
        _plan_outcome(f"plan:task-{index}", status) for index, status in enumerate(statuses)
    ]

    assert reduce_run_status(outcomes, warnings, reported) == expected
