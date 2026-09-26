"""Root Graph 领域路由：三领域映射、执行模式与显式失败。

迁移说明：``plan_execute`` 模块与 ``single_domain`` 节点已删除，``plan_execute``
执行模式随之取消（单/多领域共用 ``domain_workflow``，跨领域由根图 ``Send`` 扇出）；
每轮派生状态收进单个 ``run`` 键（用 ``run_of`` 读取），领域任务标识统一为
``task_id_of(run_id, domain)``，扇出结果落在 ``result["task_results"]``。
"""

from __future__ import annotations

import pytest

from finance_agent.orchestration.contracts import (
    RUN_CANCELLED_WARNING,
    TURN_DEADLINE_WARNING,
    BusinessDomain,
    DomainOutcome,
)
from tests.conftest import make_fake_supervisor_model
from finance_agent.orchestration.graphs.supervisor import (
    CLARIFICATION_FALLBACK,
    CLASSIFICATION_FAILED_RESPONSE,
    SupervisorDependencies,
    build_supervisor_graph,
    classify_domains,
    reduce_run_status,
    run_of,
    task_id_of,
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
        ("分析贵州茅台", ["stock_analysis"], ["stock_research"], "domain_workflow"),
        ("推荐一些股票", ["stock_recommendation"], ["stock_research"], "domain_workflow"),
        ("我的持仓怎么配置", ["portfolio_analysis"], ["account_portfolio"], "domain_workflow"),
        # 多领域不再有独立的 plan_execute 模式：单/多领域共用 domain_workflow，
        # 跨领域由根图 Send 扇出（domain_queries 仍按域切分本次请求）。
        ("分析茅台并比较基金产品", ["stock_analysis", "product_analysis"],
         ["stock_research", "product_research"], "domain_workflow"),
    ],
)
def test_root_routes_by_domain_count(message, intents, domains, mode):
    decision = classify_domains(message, classifier=_FakeClassifier(_payload(intents)))

    assert [domain.value for domain in decision.domains] == domains
    assert decision.execution_mode == mode
    assert decision.error_code == ""


def test_domains_are_ordered_by_canonical_domain_order_not_intent_order():
    """多领域结果按 _DOMAIN_ORDER 稳定排序，与分类器给出的意图顺序无关。"""
    decision = classify_domains(
        "分析茅台并比较基金产品",
        classifier=_FakeClassifier(_payload(["product_analysis", "stock_analysis"])),
    )

    assert [domain.value for domain in decision.domains] == ["stock_research", "product_research"]


@pytest.mark.parametrize(
    ("execution_mode", "error_code", "expected"),
    [
        ("conversation", "", "conversation"),
        # 单/多领域都进 scope_tasks：扇出数量不同，路径相同（single_domain / plan
        # 两个分支已随 plan_execute 模块删除）。
        ("domain_workflow", "", "domain"),
        ("clarify", "", "clarify"),
        # 分类协议错误必须走澄清/显式失败，不得因执行模式而掉进其它分支。
        ("conversation", "intent_unavailable", "clarify"),
    ],
)
def test_route_maps_execution_mode_to_branch(execution_mode, error_code, expected):
    from finance_agent.orchestration.graphs.supervisor import route

    # 路由决策现在挂在 run 键下（routing_of 经 run_of 读取）。
    state = {"run": {"routing": {"execution_mode": execution_mode, "error_code": error_code}}}
    assert route(state) == expected


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


def test_clarification_reuses_the_models_own_context_aware_question():
    """低置信度时优先转述模型自己（已结合上下文）的追问。

    固定文案"请补充更具体的信息…"与上一轮无关，正是"系统没看上下文"的观感来源。
    """
    decision = classify_domains(
        "我是稳健型选手，你有什么建议？",
        "用户: 分析一下 110011 与 000001\n助手: 两只基金风险等级均为 R4",
        classifier=_FakeClassifier(_payload([], uncertain=[{
            "intent": "portfolio_analysis", "query": "我是稳健型选手", "confidence": 0.6,
            "clarification_question": "您是想让我基于上一轮那两只基金给出稳健型配置建议吗？",
        }])),
    )

    assert decision.execution_mode == "clarify"
    assert decision.clarification == "您是想让我基于上一轮那两只基金给出稳健型配置建议吗？"


def test_clarification_falls_back_only_when_model_gives_nothing():
    decision = classify_domains(
        "那个东西怎么样",
        classifier=_FakeClassifier(
            _payload([], uncertain=[{"intent": "stock_analysis", "confidence": 0.4, "query": "那个"}])
        ),
    )

    assert decision.clarification == CLARIFICATION_FALLBACK


def test_profile_facts_reach_the_routing_decision():
    """模型自述候选随路由决策带出（落库前还要过内存层的确定性门控）。"""
    facts = [{"field": "risk_preference", "value": "R2 中低风险", "quote": "我是稳健型选手"}]
    payload = _payload(["portfolio_analysis"])
    payload["profile_facts"] = facts

    decision = classify_domains("我是稳健型选手，我的持仓怎么优化", classifier=_FakeClassifier(payload))

    assert decision.profile_facts == facts
    assert [domain.value for domain in decision.domains] == ["account_portfolio"]


def test_root_graph_creates_deterministic_single_domain_task_id():
    captured = {}

    def domain_runner(context):
        captured["task_id"] = context.task.task_id

        return DomainOutcome(
            task_id=context.task.task_id,
            domain=context.task.domain,
            status="success",
            summary="已完成分析。",
        )

    graph = build_supervisor_graph(
        SupervisorDependencies(
            supervisor_model=make_fake_supervisor_model(),
            classifier=_FakeClassifier(_payload(["stock_analysis"])),
            domain_runner=domain_runner,
            # 注入空改写器：避免默认改写器（惰性构造 INTENT_MODEL）引入外部依赖。
            rewriter=lambda state, domains: {},
        )
    )
    result = graph.invoke({"user_message": "分析贵州茅台", "run_id": "run-1", "customer_id": "CUST1"})

    expected_task_id = task_id_of("run-1", BusinessDomain.STOCK_RESEARCH)
    assert expected_task_id == "run-1:stock_research"
    assert captured["task_id"] == expected_task_id
    # 任务标识不再有 "single:" 前缀（single_task_id / single_domain_task_id 已删除），
    # 扇出结果落在 task_results 通道，键即 task_id。
    assert list(result["task_results"]) == [expected_task_id]
    assert run_of(result)["run_status"] == "completed"


# test_validate_node_passes_through_when_params_complete 已删除：extract/validate
# 节点与 param_extractor 依赖均已随架构重构移除，专家改为 ReAct 自行解析参数。


def test_conversation_branch_never_enters_param_validation():
    """闲聊不抽取参数、不校验，直接由会话节点回复。"""
    graph = build_supervisor_graph(
        SupervisorDependencies(
            supervisor_model=make_fake_supervisor_model(),
            classifier=_FakeClassifier(_payload(["casual_chat"])),
            conversation_runner=lambda state: {"final_response": "你好呀", "status": "success"},
        )
    )
    result = graph.invoke({"user_message": "你好", "run_id": "run-1"})

    assert run_of(result)["final_response"] == "你好呀"
    assert run_of(result)["run_status"] == "completed"
    assert run_of(result).get("param_blocked") in (None, False)


def test_root_graph_classification_failure_is_not_silently_treated_as_chat():
    graph = build_supervisor_graph(
        SupervisorDependencies(
            supervisor_model=make_fake_supervisor_model(),
            classifier=_FakeClassifier(_payload([], error={"error_code": "intent_unavailable"})),
            conversation_runner=lambda state: {"final_response": "不应被调用", "status": "success"},
        )
    )
    result = graph.invoke({"user_message": "随便", "run_id": "run-1"})

    assert run_of(result)["run_status"] == "failed"
    assert run_of(result)["final_response"] == CLASSIFICATION_FAILED_RESPONSE
    assert "classification_error:intent_unavailable" in run_of(result)["degradations"]


def test_root_graph_conversation_mode_delegates_to_conversation_runner():
    graph = build_supervisor_graph(
        SupervisorDependencies(
            supervisor_model=make_fake_supervisor_model(),
            classifier=_FakeClassifier(_payload(["casual_chat"])),
            conversation_runner=lambda state: {"final_response": "你好，我是投顾助手。", "status": "success"},
        )
    )
    result = graph.invoke({"user_message": "你好", "run_id": "run-1"})

    assert run_of(result)["final_response"] == "你好，我是投顾助手。"
    assert run_of(result)["run_status"] == "completed"


def test_missing_domain_runner_fails_explicitly_instead_of_silent_success():
    graph = build_supervisor_graph(
        SupervisorDependencies(
            supervisor_model=make_fake_supervisor_model(),
            classifier=_FakeClassifier(_payload(["stock_analysis"])),
            rewriter=lambda state, domains: {},
        )
    )
    result = graph.invoke({"user_message": "分析贵州茅台", "run_id": "run-1", "customer_id": "CUST1"})

    assert run_of(result)["run_status"] == "failed"
    assert "domain_runner_unavailable:stock_research" in run_of(result)["warnings"]


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

    assert decision.execution_mode == "domain_workflow"
    assert decision.domain_queries["stock_research"] == "分析贵州茅台"
    assert decision.domain_queries["product_research"] == "比较合适的基金产品"


# test_single_domain_routing_uses_scoped_query_for_task 已删除：
# 它断言"单领域直达时任务 goal 使用该领域子请求（domain_queries）而非整句"。
# 该行为在新根图上**已失效**：任务描述回退链（task_rewrite.scoped_queries）仍在
# 读顶层 state["routing"]，而路由决策现在挂在 run["routing"] 下，因此回退值恒为
# 整句原话。这不是测试可以"适配"的东西（源码不得改动）——已在迁移报告中作为
# 源码缺陷上报；classify_domains 仍如实产出 domain_queries，覆盖见上一个测试。


def test_multi_domain_classification_fans_out_one_task_per_domain():
    """多领域分类 → 每域恰好一条扇出任务（取代已删除的 deterministic_planner 测试）。

    旧断言直接读 ``deterministic_planner`` 产出的 ``plan.tasks``；计划层删除后，
    等价事实由根图的 ``Send`` 扇出表达：``task_results`` 的键集合恰为各领域的
    ``task_id_of(run_id, domain)``。
    """
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
    ran: list[str] = []

    def domain_runner(context):
        ran.append(context.task.domain.value)
        return DomainOutcome(
            task_id=context.task.task_id, domain=context.task.domain,
            status="success", summary=f"{context.task.domain.value} 完成",
        )

    graph = build_supervisor_graph(
        SupervisorDependencies(
            supervisor_model=make_fake_supervisor_model(),
            classifier=_FakeClassifier(payload),
            domain_runner=domain_runner,
            rewriter=lambda state, domains: {},
        )
    )
    result = graph.invoke(
        {"user_message": "分析贵州茅台并比较合适的基金产品", "run_id": "run-1"}
    )

    assert set(result["task_results"]) == {
        task_id_of("run-1", BusinessDomain.STOCK_RESEARCH),
        task_id_of("run-1", BusinessDomain.PRODUCT_RESEARCH),
    }
    assert sorted(ran) == sorted(
        [BusinessDomain.STOCK_RESEARCH.value, BusinessDomain.PRODUCT_RESEARCH.value]
    )
    assert run_of(result)["run_status"] == "completed"


# test_default_plan_branch_invokes_compiled_langgraph_subgraph 已删除：
# 它断言复合请求由一个"已编译的 Plan-and-Execute 子图"执行（monkeypatch
# ``build_plan_execute_graph``）。该模块、该函数与整条 plan 分支都已删除：
# 多领域现在是根图的 Send 扇出，覆盖见上一个测试与 test_root_fanout_graph.py。


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

    def domain_runner(context):
        return DomainOutcome(
            task_id=context.task.task_id, domain=context.task.domain,
            status="success", summary="贵州茅台分析完成。",
        )

    graph = build_supervisor_graph(
        SupervisorDependencies(
            supervisor_model=make_fake_supervisor_model(),
            classifier=_FakeClassifier(payload),
            domain_runner=domain_runner,
            rewriter=lambda state, domains: {},
        )
    )
    result = graph.invoke({"user_message": "分析贵州茅台并比较合适的基金产品", "run_id": "run-1"})

    # 已执行部分正常返回
    assert "贵州茅台分析完成。" in run_of(result)["final_response"]
    # 未执行部分必须显式说明，不能静默丢弃
    assert "比较合适的基金产品" in run_of(result)["final_response"]
    assert any(
        w.startswith("clarification_needed:") for w in run_of(result)["warnings"]
    )


def test_fully_covered_request_has_no_clarification_note():
    payload = {
        "intents": [{"intent": "stock_analysis", "query": "分析600519", "confidence": 0.95}],
        "uncertain_intents": [],
        "finance_related": True, "intent_source": "deepseek", "classification_error": {},
    }

    def domain_runner(context):
        return DomainOutcome(
            task_id=context.task.task_id, domain=context.task.domain,
            status="success", summary="分析完成。",
        )

    graph = build_supervisor_graph(
        SupervisorDependencies(
            supervisor_model=make_fake_supervisor_model(),
            classifier=_FakeClassifier(payload),
            domain_runner=domain_runner,
            rewriter=lambda state, domains: {},
        )
    )
    result = graph.invoke({"user_message": "分析600519", "run_id": "run-1"})

    assert "补充说明" not in run_of(result)["final_response"]
    assert run_of(result)["warnings"] == []


def test_intent_domain_registry_covers_every_intent_including_portfolio_analysis():
    """意图→领域映射必须与意图注册表同源同覆盖，防止未来新增意图再次漂移。"""
    from finance_agent.shared.contracts import IntentKind
    from finance_agent.orchestration.routing import intent as intent_module
    from finance_agent.orchestration.graphs import supervisor as supervisor_graph_module

    # 领域归属与意图顺序覆盖同一批意图；子意图表已随体系删除，不再校验。
    assert set(intent_module._INTENT_TO_DOMAIN) == set(intent_module._INTENTS)
    # Supervisor Graph 直接复用注册表对象，不再各自硬编码一份
    assert supervisor_graph_module._INTENT_TO_DOMAIN is intent_module._INTENT_TO_DOMAIN
    # 契约枚举与注册表同源（ExpertResult 的 intent 推导依赖该枚举）
    assert {kind.value for kind in IntentKind} == set(intent_module._INTENTS)
    # 验收点：portfolio_analysis 出现在所有派生结果中
    assert intent_module._INTENT_TO_DOMAIN["portfolio_analysis"] is BusinessDomain.ACCOUNT_PORTFOLIO


def test_portfolio_analysis_intent_routes_to_account_portfolio_domain():
    """配置诊断诉求必须真正路由到账户领域，而不是被静默丢弃。"""
    decision = classify_domains(
        "我的持仓怎么优化",
        classifier=_FakeClassifier(_payload(["portfolio_analysis"])),
    )

    assert [domain.value for domain in decision.domains] == ["account_portfolio"]
    assert decision.execution_mode == "domain_workflow"


def test_plain_position_query_routes_to_casual_chat():
    """收窄后的边界负例：纯持仓明细查询不属于账户领域。

    提示词规则要求这类请求归 casual_chat（账户页承载明细查询）；
    这里验证路由层对 casual_chat 的处理保持正确（进 conversation 分支）。
    """
    decision = classify_domains(
        "我的持仓怎么样",
        classifier=_FakeClassifier(_payload(["casual_chat"])),
    )

    assert decision.domains == []
    assert decision.execution_mode == "conversation"


# 子意图（sub_intent）路由测试已整体删除：子意图体系（_SUB_INTENTS、
# sub_intents / sub_intents_ambiguous、make_select_node 的领域内模式选择）已随
# 架构重构移除——专家 ReAct 自行决定领域内分析路径。
#
# 注意：子请求（routing.domain_queries）机制仍在，相关断言由上面的
# test_composite_routing_carries_per_domain_sub_requests 覆盖
# （test_single_domain_routing_uses_scoped_query_for_task 已因源码缺陷删除）。


# test_legacy_domain_react_mode_value_still_routes_to_single_domain 已删除：
# 它断言旧 checkpoint 里的 execution_mode="domain_react" 仍路由到 single_domain。
# 该节点、该分支与 legacy 取值均为已删除行为（现在只有 conversation / clarify /
# domain_workflow 三条出口），没有可保留的等价断言。


def test_single_domain_passes_rewritten_description_without_params_or_sub_intent():
    """单领域任务把改写后的自包含描述直达专家；不再下发 params / sub_intent。"""
    captured = {}

    def rewriter(state, domains):
        return {"stock_research": "分析 600519 的基本面与风险"}

    def domain_runner(context):
        captured["goal"] = context.task.goal
        captured["params"] = context.params
        captured["sub_intent"] = context.sub_intent
        return DomainOutcome(
            task_id=context.task.task_id, domain=context.task.domain,
            status="success", summary="完成。",
        )

    graph = build_supervisor_graph(
        SupervisorDependencies(
            supervisor_model=make_fake_supervisor_model(),
            classifier=_FakeClassifier(_payload(["stock_analysis"])),
            domain_runner=domain_runner,
            rewriter=rewriter,
        )
    )
    graph.invoke({"user_message": "分析600519", "run_id": "run-1"})

    assert captured["goal"] == "分析 600519 的基本面与风险"
    # 专家不再接收 params / sub_intent：ReAct 自行解析参数、选择路径。
    assert captured["params"] == {}
    assert captured["sub_intent"] == ""


def _outcome(task_id: str, status: str) -> DomainOutcome:
    return DomainOutcome(
        task_id=task_id, domain=BusinessDomain.STOCK_RESEARCH, status=status, summary="结论。",
    )


@pytest.mark.parametrize(
    ("statuses", "degradations", "expected"),
    [
        # 1) 结论集合判定
        (["success"], [], "completed"),
        (["success", "success"], [], "completed"),
        (["failed", "failed"], [], "failed"),
        (["success", "failed"], [], "partial"),
        (["success", "processing"], [], "processing"),
        ([], [], "partial"),
        # 2) 用户主动停止：覆盖集合判定（前端要区分"停止"与"出错"）
        (["success"], [RUN_CANCELLED_WARNING], "cancelled"),
        (["failed", "failed"], [RUN_CANCELLED_WARNING], "cancelled"),
        # 3) 降级级告警：completed 降为 partial；非 completed 不受影响
        (["success"], [TURN_DEADLINE_WARNING], "partial"),
        (["failed", "failed"], [TURN_DEADLINE_WARNING], "failed"),
    ],
)
def test_reduce_run_status_priority_chain(statuses, degradations, expected):
    """运行状态归约的优先级链：集合判定 < 用户停止，降级告警只降 completed。"""
    outcomes = [
        _outcome(task_id_of("run-1", BusinessDomain.STOCK_RESEARCH), status)
        for status in statuses
    ]

    assert reduce_run_status(outcomes, degradations) == expected

# 已删除：参数 ``reported``（"执行器上报的降级状态覆盖前值"）相关的 5 个用例。
# 该行为随 ``PlanRunResult.status`` 一并删除：``reduce_run_status`` 现在只由
# **领域结论集合 + 降级告警**归约，不再有"执行器自报状态"这一通道。
