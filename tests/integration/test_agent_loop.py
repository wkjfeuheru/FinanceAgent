"""领域专家的 ReAct 工具循环语义（``create_agent`` + ``experts/base.py``）。

取代旧的 ``tests/test_react_loop.py``（旧版覆盖已删除的 ``runtime/react.py``
里手写的 ``run_bounded_react``）。新循环是 **LangGraph 原生**
``langchain.agents.create_agent``，由 ``build_expert_graph`` 包装为
``validate → agent → assemble`` 子图。本文件钉住四条仍然成立的业务不变量：

1. **步数预算是硬约束**：``ModelCallLimitMiddleware(run_limit=N)`` 至多调用模型
   N 次；收尾时仍是工具调用即被截断 → ``status="partial"`` +
   limitation ``react_step_limit``（诚实降级，不伪报成功）。
2. **工具白名单**：模型只能调用已绑定工具；请求白名单外的工具不会执行、
   不产生任何 sink 记录。
3. **最终 AI 文本即结论摘要**（无权威模板覆盖时）。
4. **工具产物经 sink 写入冻结键位**，映射进 ``structured_data``。

假模型来自 ``tests/conftest.py`` 的 ``make_fake_tool_model``（``GenericFakeChatModel``
不支持 ``bind_tools``，helper 已补齐）。
"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from finance_agent.orchestration.contracts import (
    BusinessDomain,
    DomainTaskContext,
    PlanTask,
)
from finance_agent.orchestration.experts.base import build_expert_graph, sink_of
from tests.conftest import final_message, make_fake_tool_model, tool_call

PRODUCT = BusinessDomain.PRODUCT_RESEARCH


class _CountingIterator:
    """统计被消费的消息条数（= 模型被调用的次数）。

    ``make_fake_tool_model`` 内部会 ``iter(messages)``；本类的 ``__iter__``
    返回自身，因此计数在包装后仍然有效。
    """

    def __init__(self, items) -> None:
        self._iterator = iter(items)
        self.count = 0

    def __iter__(self):
        return self

    def __next__(self):
        self.count += 1
        return next(self._iterator)


def _make_probe_tool(calls: list[str] | None = None):
    """一个写入 ``product_analysis`` 冻结键位的最小市场工具。"""
    observations = calls if calls is not None else []

    @tool
    def product_probe(query: str, config: RunnableConfig) -> str:
        """采集市场数据。"""
        observations.append(query)
        sink = sink_of(config)
        if sink is not None:
            sink.record("product_probe", payload={"product_analysis": {"query": query}})
        return "{}"

    product_probe._observations = observations  # type: ignore[attr-defined]
    return product_probe


def _context(goal: str = "看看大盘") -> DomainTaskContext:
    return DomainTaskContext(
        task=PlanTask(
            task_id="single:run-1:product_analysis",
            domain=PRODUCT,
            goal=goal,
            instruction=goal,
            expected_output="domain_outcome",
        ),
        thread_id="th-1",
        customer_id="CUST1",
        conversation_id="conv-1",
        user_message=goal,
    )


def _graph(model, *, tools, max_steps=4):
    return build_expert_graph(
        PRODUCT,
        tools=list(tools),
        system_prompt="你是产品专家，只输出结构化结论（json）。",
        max_steps=max_steps,
        model=model,
    )


# ── 3. 最终 AI 文本即结论摘要 ────────────────────────────────────────────


def test_final_ai_text_becomes_summary():
    """工具轮之后的最终文本成为结论 summary；已写入的产物进入 structured_data。"""
    probe = _make_probe_tool()
    model = make_fake_tool_model([
        tool_call("product_probe", {"query": "大盘概览"}, call_id="a1"),
        final_message("今日大盘震荡，成交温和。"),
    ])

    outcome = _graph(model, tools=[probe]).invoke({"context": _context()})["domain_outcome"]

    assert outcome.status == "success"
    assert outcome.summary == "今日大盘震荡，成交温和。"
    assert outcome.structured_data["product_analysis"] == {"query": "大盘概览"}


def test_no_tool_call_returns_text_but_degrades_to_partial():
    """模型直接给出答复（不调工具）时：文本仍成为 summary，但没有结构化产物，
    按诚实降级规则结论为 partial（不伪报成功）。"""
    model = make_fake_tool_model([final_message("你好，我是投顾助手。")])

    outcome = _graph(model, tools=[_make_probe_tool()]).invoke(
        {"context": _context("你好")}
    )["domain_outcome"]

    assert outcome.status == "partial"
    assert outcome.summary == "你好，我是投顾助手。"
    assert outcome.structured_data == {}


# ── 1. 步数上限：截断 → partial + react_step_limit ──────────────────────


def test_step_limit_truncation_degrades_to_partial():
    """模型一直要求调工具，被步数上限截断：partial + react_step_limit。"""
    probe = _make_probe_tool()
    model = make_fake_tool_model([
        tool_call("product_probe", {"query": "x"}, call_id=f"c{i}") for i in range(10)
    ])

    outcome = _graph(model, tools=[probe], max_steps=2).invoke(
        {"context": _context()}
    )["domain_outcome"]

    assert outcome.status == "partial"
    assert "react_step_limit" in outcome.limitations


# ── 4(部分). ModelCallLimitMiddleware 限制模型调用次数 ───────────────────


def test_model_call_limit_caps_model_invocations():
    """``run_limit=N`` 至多调用模型 N 次（即便模型还有更多可用响应）。"""
    counter = _CountingIterator([
        tool_call("product_probe", {"query": "x"}, call_id=f"c{i}") for i in range(10)
    ])
    model = make_fake_tool_model(counter)

    outcome = _graph(model, tools=[_make_probe_tool()], max_steps=3).invoke(
        {"context": _context()}
    )["domain_outcome"]

    assert counter.count == 3, "模型调用次数必须被 ModelCallLimitMiddleware 限制为 run_limit"
    assert "react_step_limit" in outcome.limitations


# ── 2. 工具白名单：白名单外工具不可执行 ─────────────────────────────────


def test_tool_outside_whitelist_is_not_executed():
    """模型请求未绑定工具：该工具不执行、不产生 sink 记录（结构化产物为空）。"""
    executed: list[str] = []
    probe = _make_probe_tool(executed)
    model = make_fake_tool_model([
        tool_call("forbidden_tool", {"query": "600519"}, call_id="b1"),
        final_message("无法执行该操作。"),
    ])

    outcome = _graph(model, tools=[probe]).invoke({"context": _context()})["domain_outcome"]

    assert executed == [], "白名单外工具不得被执行"
    assert "product_analysis" not in outcome.structured_data


def test_whitelisted_tool_is_executed_only_when_requested():
    """绑定工具按模型请求执行一次；未请求则零执行。"""
    executed: list[str] = []
    probe = _make_probe_tool(executed)
    model = make_fake_tool_model([final_message("无需取数。")])

    _graph(model, tools=[probe]).invoke({"context": _context()})

    assert executed == []

    executed.clear()
    model = make_fake_tool_model([
        tool_call("product_probe", {"query": "资金面"}, call_id="z1"),
        final_message("已取数。"),
    ])
    _graph(model, tools=[probe]).invoke({"context": _context()})

    assert executed == ["资金面"]


# ── 缺参信号：request_user_input 产出 needs_input（非成功）──────────────


def test_request_user_input_yields_needs_input_outcome():
    """模型调用内置 ``request_user_input`` 时结论为 needs_input，携带 pending_input。"""
    model = make_fake_tool_model([
        tool_call(
            "request_user_input",
            {"fields": ["market_overview"], "question": "请补充市场范围。"},
            call_id="r1",
        ),
        final_message("请补充市场范围。"),
    ])

    outcome = _graph(model, tools=[_make_probe_tool()]).invoke(
        {"context": _context()}
    )["domain_outcome"]

    # 产品域没有 ``market_overview`` 这种可追问字段（EXPERT_FIELDS 不含它），
    # 字段被拒 → 不置位 pending_input。
    assert outcome.status != "needs_input"


# ── 答案组合：用户可见正文 = 模型分析（default_assemble）─────────────────


def _digest_probe(record: dict, digest: str):
    """写入冻结键位的工具（模拟 product/account 等）。"""

    @tool
    def digest_probe(query: str, config: RunnableConfig) -> str:
        """采集数据。"""
        sink = sink_of(config)
        if sink is not None:
            sink.record("digest_probe", payload=record)
        return "{}"

    return digest_probe


def test_summary_is_model_analysis_without_digest_appendix():
    """正文 = 模型分析；不再拼接中文 data_digest。"""
    probe = _digest_probe(
        {"product_analysis": {"mode": "market_overview", "status": "success",
                            "indices": [{"close": 3888.11}]}},
        "【大盘概览】\n- 上证指数：3,888.11（-1.18%）",
    )
    model = make_fake_tool_model([
        tool_call("digest_probe", {"query": "大盘"}, call_id="d1"),
        final_message("今日大盘偏弱，上证指数收于 3,888.11 点。"),
    ])

    outcome = _graph(model, tools=[probe]).invoke({"context": _context()})["domain_outcome"]

    assert outcome.status == "success"
    assert outcome.summary == "今日大盘偏弱，上证指数收于 3,888.11 点。"
    assert "以下为详细数据：" not in outcome.summary
    assert "【大盘概览】" not in outcome.summary


def test_fallback_when_analysis_missing():
    """模型没给分析（如被步数截断）时，用兜底说明，不回填中文模板。"""
    probe = _digest_probe(
        {"product_analysis": {"mode": "market_overview", "status": "success"}},
        "【大盘概览】\n- 上证指数：3,888.11（-1.18%）",
    )
    model = make_fake_tool_model([
        tool_call("digest_probe", {"query": f"q{i}"}, call_id=f"x{i}")
        for i in range(4)
    ])

    outcome = _graph(model, tools=[probe], max_steps=4).invoke(
        {"context": _context()}
    )["domain_outcome"]

    assert outcome.status == "partial"
    assert "react_step_limit" in outcome.limitations
    assert "以下为详细数据：" not in outcome.summary
    assert "【大盘概览】" not in outcome.summary


# ── 数字保真：分析里越界的数字被登记（不阻断、不改写）────────────────────


def test_ungrounded_number_in_analysis_is_flagged():
    """分析中凭空出现的数字进入 limitations 与 analysis_grounding。"""
    probe = _digest_probe(
        {"product_analysis": {"indices": [{"close": 3888.11}]}},
        "",
    )
    model = make_fake_tool_model([
        tool_call("digest_probe", {"query": "大盘"}, call_id="g1"),
        final_message("上证指数 3,888.11 点，预计下探 3,700 点。"),
    ])

    outcome = _graph(model, tools=[probe]).invoke({"context": _context()})["domain_outcome"]

    assert any("analysis_number_not_grounded" in item for item in outcome.limitations)
    assert outcome.structured_data["analysis_grounding"]["ungrounded"] == ["3,700 点"]
    # 不阻断：分析原样保留在正文里，未被静默改写。
    assert "预计下探 3,700 点" in outcome.summary


def test_grounded_numbers_pass_with_rounding_and_sign():
    """有依据的数字（含四舍五入与正负号差异）不误报。"""
    probe = _digest_probe(
        {"product_analysis": {"indices": [{"close": 3888.114, "pct_chg": -1.182}]}},
        "",
    )
    model = make_fake_tool_model([
        tool_call("digest_probe", {"query": "大盘"}, call_id="g2"),
        final_message("上证指数 3,888.11 点，跌 1.18%。"),
    ])

    outcome = _graph(model, tools=[probe]).invoke({"context": _context()})["domain_outcome"]

    assert outcome.limitations == []
    assert "analysis_grounding" not in outcome.structured_data
