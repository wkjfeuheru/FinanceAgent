"""业务领域请求场景目录：单一 / 复合 / 关键参数缺失追问。

这是"用户会怎么问 → 系统应如何路由"的可回归目录，覆盖四个业务领域与闲聊，
并固化缺参追问（HITL interrupt）的三条路径：挂起 / 补答执行 / 取消收尾。

分类器在本测试中被打桩为**该问句在真实分类器下应产生的意图**（与
``routing.intent._INTENT_TO_DOMAIN`` 同一事实源），因此这里锁定的不是模型
输出，而是"意图 → 领域 → 执行/追问"这段确定性路由逻辑；模型侧的非确定性
不进入本测试，交由联网验收覆盖。

架构变更后：参数提取下沉到领域专家 ReAct 循环，supervisor 不再有 ``extract``/
``validate`` 节点与 ``ExtractedParams``。"是否缺参"如今由领域结论
``DomainOutcome.status="needs_input"`` 表达，由 ``converge`` 节点判定与计数、
``ask`` 节点统一弹窗（``interrupt`` 的唯一宿主）并按域重跑（细节见
``test_check_outcomes_graph.py``）。本文件聚焦
"每类用户问题归到哪个领域、是否追问"的可读目录。
"""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from finance_agent.orchestration.contracts import BusinessDomain, DomainOutcome
from finance_agent.orchestration.graphs.supervisor import (
    PARAM_CANCELLED_RESPONSE,
    SupervisorDependencies,
    build_supervisor_graph,
    run_of,
)
from finance_agent.orchestration.needs_input import build_form


# ── 测试替身 ──────────────────────────────────────────────────

class _StubClassifier:
    """按预设意图输出结构化分类结果（模拟真实分类器的协议形状）。"""

    def __init__(self, intents: list[str], *, queries: dict[str, str] | None = None) -> None:
        self._intents = intents
        self._queries = queries or {}

    def classify_intents(self, message: str, context_summary: str = "") -> dict:
        return {
            "intents": [
                {
                    "intent": intent,
                    "query": self._queries.get(intent, message),
                    "confidence": 0.9,
                }
                for intent in self._intents
            ],
            "uncertain_intents": [],
            "finance_related": True,
            "intent_source": "deepseek",
            "classification_error": {},
        }


class _RecordingRunner:
    """记录每个被执行的领域任务；恒成功（用于"路由 + 执行"断言）。"""

    def __init__(self) -> None:
        self.domains: list[str] = []
        self.contexts: list = []

    def __call__(self, context) -> DomainOutcome:
        self.domains.append(context.task.domain.value)
        self.contexts.append(context)
        return DomainOutcome(
            task_id=context.task.task_id, domain=context.task.domain,
            status="success", summary="已完成分析。",
        )


class _StockNeedsInputRunner:
    """股票首次缺标的、补答后成功；其它领域恒成功。"""

    def __init__(self) -> None:
        self.domains: list[str] = []
        self.contexts: list = []

    def __call__(self, context) -> DomainOutcome:
        self.domains.append(context.task.domain.value)
        self.contexts.append(context)
        domain = context.task.domain
        answers = dict(context.clarification_answers or {})
        if domain is BusinessDomain.STOCK_RESEARCH and not answers:
            return DomainOutcome(
                task_id=context.task.task_id, domain=domain, status="needs_input",
                summary="请补充股票标的。",
                structured_data={
                    "pending_input": build_form([(domain, ("stock_target",))]),
                },
            )
        return DomainOutcome(
            task_id=context.task.task_id, domain=domain, status="success",
            summary="已完成分析。",
        )


def _build(intents, *, runner=None, queries=None, checkpointer="default"):
    return build_supervisor_graph(
        SupervisorDependencies(
            classifier=_StubClassifier(intents, queries=queries),
            domain_runner=runner or _RecordingRunner(),
            conversation_runner=lambda state: {"final_response": "你好", "status": "success"},
            # 空改写器：避免默认改写器（惰性构造 INTENT_MODEL）引入外部依赖。
            rewriter=lambda state, domains: {},
        ),
        checkpointer=InMemorySaver() if checkpointer == "default" else checkpointer,
    )


def _inputs(thread: str, message: str, **extra):
    return {
        "user_message": message, "run_id": f"run-{thread}", "customer_id": "CUST1",
        "conversation_id": f"conv-{thread}", "thread_id": thread, **extra,
    }


def _config(thread: str) -> dict:
    return {"configurable": {"thread_id": thread}}


# ── 单一领域：问候语 → 应归入的领域（不涉及追问）────────────────
# 每条：(用例名, 用户问题, 真实分类器下的意图, 期望领域)
SINGLE_DOMAIN_CASES = [
    # 股票研究：给代码 / 给名称 / 要候选推荐 / 只给分析维度
    ("股票-按代码", "分析600519", "stock_analysis", "stock_research"),
    ("股票-按名称", "分析贵州茅台", "stock_analysis", "stock_research"),
    ("股票-候选推荐", "推荐几只白酒龙头股", "stock_recommendation", "stock_research"),
    # 市场洞察：四种模式
    ("市场-大盘概览", "今天大盘怎么样", "market_insight", "market_insight"),
    ("市场-情绪", "最近市场情绪如何", "market_insight", "market_insight"),
    ("市场-资金面", "最近资金面如何", "market_insight", "market_insight"),
    ("市场-政策事件", "最近有什么政策影响市场", "market_insight", "market_insight"),
    # 产品研究
    ("产品-查询", "分析一下华夏成长基金", "product_analysis", "product_research"),
    # 账户/持仓：只读
    ("账户-配置诊断", "帮我看看持仓怎么配置", "portfolio_analysis", "account_portfolio"),
]


@pytest.mark.parametrize(
    "name,message,intent,domain",
    SINGLE_DOMAIN_CASES,
    ids=[case[0] for case in SINGLE_DOMAIN_CASES],
)
def test_single_domain_request_routes_and_executes(name, message, intent, domain):
    """单一领域请求：路由到正确领域并真正执行。"""
    runner = _RecordingRunner()
    graph = _build([intent], runner=runner, queries={intent: message})

    result = graph.invoke(_inputs(f"s-{name}", message), _config(f"s-{name}"))

    assert not result.get("__interrupt__"), f"{name} 不应追问"
    assert runner.domains == [domain], f"{name} 应执行 {domain}，实际 {runner.domains}"


def test_conversation_request_executes_no_domain():
    """闲聊/FAQ 请求：不路由到业务领域。"""
    runner = _RecordingRunner()
    graph = _build(["casual_chat"], runner=runner)

    result = graph.invoke(_inputs("s-chat", "你好呀"), _config("s-chat"))

    assert not result.get("__interrupt__")
    assert runner.domains == []
    assert run_of(result)["final_response"] == "你好"


# ── 复合领域：跨领域请求 → 扇出到每个领域且都执行 ────────────────
COMPOSITE_CASES = [
    ("股票+产品", "分析贵州茅台并比较合适的基金产品",
     ["stock_analysis", "product_analysis"], ["stock_research", "product_research"]),
    ("股票+市场", "大盘怎么样，顺便分析下600519",
     ["stock_analysis", "market_insight"], ["stock_research", "market_insight"]),
]


@pytest.mark.parametrize(
    "name,message,intents,domains",
    COMPOSITE_CASES,
    ids=[case[0] for case in COMPOSITE_CASES],
)
def test_composite_request_executes_every_domain(name, message, intents, domains):
    """复合请求：每个领域各得一条自包含任务，全部执行。"""
    runner = _RecordingRunner()
    graph = _build(intents, runner=runner)
    thread = f"c-{name}"

    result = graph.invoke(_inputs(thread, message), _config(thread))

    assert not result.get("__interrupt__"), f"{name} 不应追问"
    assert sorted(runner.domains) == sorted(domains), f"{name} 应执行全部领域，实际 {runner.domains}"


# ── 关键参数缺失 → 追问 / 补答 / 取消 ──────────────────────────
# 参数提取已下沉到专家：缺参由领域结论 ``needs_input`` 表达，经 ``converge``
# 判定、``ask`` 节点合并弹窗。这里用假领域运行器模拟专家的缺参信号。

def test_missing_stock_target_interrupts_with_form():
    """股票请求缺标的：挂起并下发追问表单（必填 stock_target）。"""
    graph = _build(["stock_analysis"], runner=_StockNeedsInputRunner())
    thread = "hitl-form"

    result = graph.invoke(_inputs(thread, "帮我做技术面分析"), _config(thread))

    interrupts = result.get("__interrupt__") or ()
    assert interrupts, "缺标的必须挂起追问"
    form = interrupts[0].value
    assert "股票标的" in form["question"]
    assert form["missing"] == ["stock_research:stock_target"]
    names = [f["name"] for f in form["fields"]]
    assert names[0] == "stock_target"
    # 同框收集可选偏好，且只有必填项被标 required。
    assert set(names) >= {"stock_target", "analysis_type", "risk_preference", "holding_period"}
    assert [f["required"] for f in form["fields"] if f["name"] == "stock_target"] == [True]


def test_resume_with_target_executes_domain():
    """补答后领域被重跑并拿到答案。"""
    runner = _StockNeedsInputRunner()
    graph = _build(["stock_analysis"], runner=runner)
    thread = "hitl-resume"

    graph.invoke(_inputs(thread, "帮我做技术面分析"), _config(thread))
    result = graph.invoke(
        Command(resume={"stock_target": "600519"}), _config(thread),
    )

    assert not result.get("__interrupt__"), "补齐后不得再次追问"
    reruns = [c for c in runner.contexts if c.clarification_answers]
    assert reruns, "补齐后必须重跑领域"
    assert reruns[0].clarification_answers["stock_target"] == "600519"


def test_cancel_resume_finishes_without_rerunning():
    """取消追问：不重跑领域，明确收尾。"""
    runner = _StockNeedsInputRunner()
    graph = _build(["stock_analysis"], runner=runner)
    thread = "hitl-cancel"

    graph.invoke(_inputs(thread, "帮我做基本面分析"), _config(thread))
    result = graph.invoke(Command(resume={"__cancel__": True}), _config(thread))

    assert not result.get("__interrupt__")
    assert run_of(result)["final_response"] == PARAM_CANCELLED_RESPONSE
    assert "param_cancelled_by_user" in run_of(result)["warnings"]
    assert not any(c.clarification_answers for c in runner.contexts), "取消后不得重跑领域"


def test_domains_without_required_params_never_interrupt():
    """市场/账户无可追问字段：任何问句都不得因缺参挂起。"""
    for intent, domain in (
        ("market_insight", "market_insight"),
        ("portfolio_analysis", "account_portfolio"),
    ):
        runner = _RecordingRunner()
        graph = _build([intent], runner=runner)
        thread = f"noint-{domain}"
        result = graph.invoke(_inputs(thread, "随便问问"), _config(thread))

        assert not result.get("__interrupt__"), f"{domain} 不应追问"
        assert runner.domains == [domain], f"{domain} 应直接执行"
