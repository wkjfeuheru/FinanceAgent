"""专家 ReAct 循环的协作式停止：宿主标记必须能中断进行中的领域分析。

产品承诺（重构决策 1）："停止生成"要真正生效——不是"不再启动新的领域"，而是**正在
跑的专家也会在下一个模型轮次边界退出**，并且已经产出的部分结论按 partial 保留。

实现方式是 ``CooperativeStopMiddleware``：``stop_check`` 经 ``RunnableConfig`` 下发，
中间件在每次模型调用前检查；命中即 ``jump_to="end"`` 结束循环并把原因码写进 sink 的
limitations，由 ``assemble`` 降级为 ``partial``。
"""

from __future__ import annotations

from finance_agent.orchestration.contracts import (
    RUN_CANCELLED_WARNING,
    TURN_DEADLINE_WARNING,
    BusinessDomain,
    DomainOutcome,
    DomainTaskContext,
    PlanTask,
)
from finance_agent.orchestration.experts.base import (
    STOP_CHECK_KEY,
    build_expert_graph,
    build_stop_middleware,
)
from tests.conftest import final_message, make_fake_tool_model, tool_call


def _context() -> DomainTaskContext:
    return DomainTaskContext(
        task=PlanTask(
            task_id="run-1:market_insight",
            domain=BusinessDomain.MARKET_INSIGHT,
            goal="看看今天大盘",
            instruction="看看今天大盘",
            expected_output="domain_outcome",
        ),
        thread_id="v1:CUST1:conv-1",
        customer_id="CUST1",
        conversation_id="conv-1",
        user_message="看看今天大盘",
    )


def _expert(messages, *, max_steps: int = 4):
    """编译一个用假模型驱动的市场专家（工具白名单为空，足够驱动循环）。"""
    return build_expert_graph(
        BusinessDomain.MARKET_INSIGHT,
        tools=[],
        system_prompt="你是市场分析助手。",
        max_steps=max_steps,
        model=make_fake_tool_model(messages),
    )


def _outcome(graph, stop_check) -> DomainOutcome:
    return graph.invoke(
        {"context": _context()},
        config={"configurable": {STOP_CHECK_KEY: stop_check}},
    )["domain_outcome"]


def test_stop_before_first_model_call_ends_loop_with_reason():
    """停止标记在下发前已置位：一次模型调用都不发生，结论按 partial 降级。"""
    graph = _expert([tool_call("noop"), final_message("不该被调用")])

    outcome = _outcome(graph, lambda: RUN_CANCELLED_WARNING)

    assert outcome.status == "partial"
    assert RUN_CANCELLED_WARNING in outcome.limitations
    assert "不该被调用" not in outcome.summary


def test_deadline_expiry_is_reported_with_its_own_reason_code():
    """截止与用户停止是两种原因码：前端要能区分"超时"与"我按了停止"。"""
    graph = _expert([final_message("不该被调用")])

    outcome = _outcome(graph, lambda: TURN_DEADLINE_WARNING)

    assert outcome.status == "partial"
    assert TURN_DEADLINE_WARNING in outcome.limitations


def test_stop_mid_loop_ends_before_the_next_model_call():
    """跑到一半被停止：下一次模型调用不再发生，sink 记录了原因码。

    这里直接驱动一个原生 ``create_agent`` 循环（带一个不发网络的探针工具）：
    第一轮模型要求调工具（循环必须继续），此时停止标记置位，中间件应当在
    **第二次模型调用之前**结束循环。
    """
    from langchain.agents import create_agent
    from langchain_core.messages import HumanMessage
    from langchain_core.tools import tool

    from finance_agent.orchestration.experts.base import SINK_KEY, ExpertSink

    tool_calls: list[str] = []

    @tool
    def probe(x: str = "") -> str:
        """记录一次工具调用。"""
        tool_calls.append(x)
        return "ok"

    state = {"calls": 0}

    def stop_check() -> str:
        state["calls"] += 1
        return "" if state["calls"] <= 1 else RUN_CANCELLED_WARNING

    sink = ExpertSink(domain=BusinessDomain.MARKET_INSIGHT)
    agent = create_agent(
        make_fake_tool_model([
            tool_call("probe", {"x": "first"}),
            final_message("这段不应被采用"),
        ]),
        tools=[probe],
        system_prompt="测试用。",
        middleware=[build_stop_middleware()],
    )

    result = agent.invoke(
        {"messages": [HumanMessage(content="开始")]},
        config={"configurable": {STOP_CHECK_KEY: stop_check, SINK_KEY: sink}},
    )

    assert tool_calls == ["first"], "被停止前的那一次工具调用应当已经发生"
    assert RUN_CANCELLED_WARNING in sink.limitations
    texts = [
        str(getattr(message, "content", "") or "")
        for message in result["messages"]
    ]
    assert "这段不应被采用" not in texts, "停止后不得再生成新的答复文本"


def test_without_stop_check_the_loop_runs_normally():
    """未注入停止查询时行为不变（多加一层检查不得影响正常路径）。"""
    graph = _expert([final_message("大盘情绪偏暖。")])

    outcome = graph.invoke({"context": _context()})["domain_outcome"]

    assert outcome.summary == "大盘情绪偏暖。"
    assert RUN_CANCELLED_WARNING not in outcome.limitations
    assert TURN_DEADLINE_WARNING not in outcome.limitations
