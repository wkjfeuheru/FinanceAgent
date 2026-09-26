"""缺参追问的 interrupt / resume / 取消 / 降级（``converge`` + ``ask`` 节点）。

取代旧的 ``tests/test_param_interrupt_graph.py``（旧版测试的是已被删除的
``validate`` 节点与 ``ExtractedParams`` 抽取通道）。新架构里"缺参"由领域专家
在 ReAct 循环中得出（``DomainOutcome.status="needs_input"``），职责由两个节点分担：

- ``converge``：缺参判定与确定性计数（弹窗预算、停止/截止、无 checkpointer 的
  降级收尾都在这里决定），并归约 ``run_status``/``warnings``/``degradations``；
- ``ask``：``interrupt`` 的**唯一**宿主，把 ``converge`` 合并出的**一张**表单
  挂起给用户，拿到答案后只重跑缺参的那些领域。

这两个节点自此取代了旧的 ``check_outcomes`` 单节点。

覆盖：
(a) 无 checkpointer → 退化为澄清式收尾（partial + param_blocked + 表单）；
(b) 有 checkpointer → 挂起，投影为 awaiting_input；
(c) 补答恢复 → 领域被**恰好重跑一次**且拿到答案，运行 completed；
(d) 取消哨兵 → PARAM_CANCELLED_RESPONSE + param_cancelled_by_user；
(e) 市场/账户永不缺参，因此永不挂起。
"""

from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from finance_agent.orchestration.contracts import BusinessDomain, DomainOutcome
from finance_agent.orchestration.graphs.supervisor import (
    PARAM_CANCELLED_RESPONSE,
    SupervisorDependencies,
    build_supervisor_graph,
    project_interrupt_state,
    run_of,
)
from finance_agent.orchestration.needs_input import build_form


class _FakeClassifier:
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
                    "confidence": 0.99,
                }
                for intent in self._intents
            ],
            "uncertain_intents": [],
            "finance_related": True,
            "intent_source": "deepseek",
            "classification_error": {},
        }


class _StockNeedsInputRunner:
    """股票首次缺参、补答后成功；市场/账户恒成功；记录每次运行的上下文。

    "首次缺参"的判据是 ``clarification_answers`` 为空——与真实专家读取
    ``DomainTaskContext.clarification_answers`` 的语义一致。
    """

    def __init__(self) -> None:
        self.contexts = []

    def __call__(self, context) -> DomainOutcome:
        self.contexts.append(context)
        domain = context.task.domain
        answers = dict(context.clarification_answers or {})
        if domain is BusinessDomain.STOCK_RESEARCH and not answers:
            return DomainOutcome(
                task_id=context.task.task_id,
                domain=domain,
                status="needs_input",
                summary="请补充股票标的。",
                structured_data={
                    "pending_input": build_form([(domain, ("stock_target",))]),
                },
            )
        target = answers.get("stock_target", "")
        summary = f"已完成分析：{target}" if target else "已完成分析。"
        return DomainOutcome(
            task_id=context.task.task_id, domain=domain, status="success", summary=summary,
        )


def _graph(intents, *, runner=None, checkpointer=None, queries=None):
    return build_supervisor_graph(
        SupervisorDependencies(
            classifier=_FakeClassifier(intents, queries=queries),
            domain_runner=runner or _StockNeedsInputRunner(),
            conversation_runner=lambda state: {"final_response": "你好", "status": "success"},
            # 注入空改写器：避免默认改写器（惰性构造 INTENT_MODEL）在测试中引入外部依赖。
            rewriter=lambda state, domains: {},
        ),
        checkpointer=checkpointer,
    )


def _inputs(thread_id: str = "t1") -> dict:
    return {
        "user_message": "帮我做技术面分析",
        "run_id": "run-1",
        "customer_id": "CUST1",
        "conversation_id": "conv-1",
        "thread_id": thread_id,
    }


def _config(thread_id: str = "t1") -> dict:
    return {"configurable": {"thread_id": thread_id}}


# ── (a) 无 checkpointer：退化为澄清式收尾 ────────────────────────────────


def test_without_checkpointer_degrades_to_partial_clarification():
    """无 checkpointer 无法 suspend/resume：把缺参问题作为回复返回并置 partial。"""
    graph = _graph(["stock_analysis"], checkpointer=None)

    result = graph.invoke(_inputs())

    assert not result.get("__interrupt__")
    assert run_of(result)["run_status"] == "partial"
    assert run_of(result)["param_blocked"] is True
    assert run_of(result)["param_missing"]["missing"] == ["stock_research:stock_target"]
    assert "股票标的" in run_of(result)["final_response"]


# ── (b) 有 checkpointer：挂起并投影为 awaiting_input ─────────────────────


def test_stock_missing_target_interrupts_with_form():
    graph = _graph(["stock_analysis"], checkpointer=InMemorySaver())

    result = graph.invoke(_inputs(), _config())

    interrupts = result.get("__interrupt__") or ()
    assert interrupts, "缺标的的股票请求必须挂起等待用户补充"
    form = interrupts[0].value
    assert form["missing"] == ["stock_research:stock_target"]
    assert [field["name"] for field in form["fields"]][0] == "stock_target"

    projected = project_interrupt_state(result, conversation_id="conv-1")
    assert projected["run_status"] == "awaiting_input"
    assert projected["pending_input"]["missing"] == ["stock_research:stock_target"]


# ── (c) 补答恢复：重跑缺参领域恰好一次 ───────────────────────────────────


def test_resume_with_target_reruns_domain_exactly_once_with_answer():
    runner = _StockNeedsInputRunner()
    graph = _graph(["stock_analysis"], runner=runner, checkpointer=InMemorySaver())
    config = _config()

    graph.invoke(_inputs(), config)
    result = graph.invoke(Command(resume={"stock_target": "600519"}), config)

    assert not result.get("__interrupt__")
    assert run_of(result)["run_status"] == "completed"
    reruns = [c for c in runner.contexts if c.clarification_answers]
    assert len(reruns) == 1, "缺参领域应被恰好重跑一次"
    assert reruns[0].clarification_answers["stock_target"] == "600519"
    assert "600519" in run_of(result)["final_response"]


def test_resume_with_domain_scoped_answer_key_is_accepted():
    """答案键兼容 ``{domain}:{field}`` 形态（``missing`` 列表的写法）。"""
    runner = _StockNeedsInputRunner()
    graph = _graph(["stock_analysis"], runner=runner, checkpointer=InMemorySaver())
    config = _config("t-scoped")

    graph.invoke(_inputs("t-scoped"), config)
    result = graph.invoke(
        Command(resume={"stock_research:stock_target": "600519"}), config,
    )

    assert run_of(result)["run_status"] == "completed"
    assert any(
        c.clarification_answers.get("stock_target") == "600519" for c in runner.contexts
    )


# ── (d) 取消哨兵 ─────────────────────────────────────────────────────────


def test_cancel_resume_finishes_without_rerunning_domain():
    runner = _StockNeedsInputRunner()
    graph = _graph(["stock_analysis"], runner=runner, checkpointer=InMemorySaver())
    config = _config("t-cancel")

    graph.invoke(_inputs("t-cancel"), config)
    result = graph.invoke(Command(resume={"__cancel__": True}), config)

    assert not result.get("__interrupt__")
    assert run_of(result)["run_status"] == "completed"
    assert run_of(result)["final_response"] == PARAM_CANCELLED_RESPONSE
    assert "param_cancelled_by_user" in run_of(result)["warnings"]
    assert not any(c.clarification_answers for c in runner.contexts), "取消后不得重跑领域"


# ── (e) 市场/账户永不缺参 ────────────────────────────────────────────────


def test_market_and_account_never_interrupt():
    for intent, domain in (
        ("market_insight", "market_insight"),
        ("portfolio_analysis", "account_portfolio"),
    ):
        thread = f"t-{domain}"
        graph = _graph([intent], checkpointer=InMemorySaver())
        result = graph.invoke(_inputs(thread), _config(thread))

        assert not result.get("__interrupt__"), f"{domain} 不应触发追问"
        assert run_of(result)["run_status"] == "completed"


# ── 结论校验：needs_input 不得被当作终态成功放行 ─────────────────────────


def test_needs_input_status_is_not_reported_as_success_without_node():
    """兜底映射：即便 ``converge`` 未拦截，needs_input 也不映射为 completed。"""
    from finance_agent.orchestration.contracts import DOMAIN_STATUS_TO_RUN_STATUS

    assert DOMAIN_STATUS_TO_RUN_STATUS["needs_input"] != "completed"
