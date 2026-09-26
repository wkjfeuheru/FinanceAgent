"""会话子图（LangGraph 原生 ``create_agent`` 工具循环）：FAQ 命中/未命中、
受信标记、模型失败降级与步数上限。

旧实现是自定义 ``run_bounded_react`` + 白名单工具执行器；重构后统一走
``create_agent``，只暴露 ``faq_search`` 一个工具，工具调用序列由假 chat 模型
脚本化驱动（系统提示词不改变假模型的固定输出）。
"""

from __future__ import annotations

from typing import Any

from finance_agent.domains.faq.contracts import FaqSearchMatch, FaqSearchResult
from finance_agent.orchestration.graphs.conversation import (
    CONVERSATION_REFUSAL,
    _CONVERSATION_PROMPT,
    build_conversation_graph,
    build_faq_tool,
    run_conversation,
)
from tests.conftest import final_message, make_fake_tool_model, tool_call

_FAQ_ANSWER = "任何声称“保证收益”的宣传都涉嫌违规。"
_NO_ANSWER = "FAQ 知识库中没有可靠答案。"


class _FakeRetriever:
    def __init__(self, result: FaqSearchResult) -> None:
        self._result = result

    def search(self, query: str, top_k: int | None = None) -> FaqSearchResult:
        del query, top_k
        return self._result


def _found_retriever() -> _FakeRetriever:
    return _FakeRetriever(
        FaqSearchResult(
            status="found",
            matches=[
                FaqSearchMatch(
                    faq_id="FAQ-001",
                    chunk_id="c1",
                    score=0.9,
                    index_version="index-1",
                    source_path="docs/faq/investment-basics.md",
                    question="什么是保证收益？",
                    answer=_FAQ_ANSWER,
                )
            ],
        )
    )


def _not_found_retriever() -> _FakeRetriever:
    return _FakeRetriever(FaqSearchResult(status="not_found", matches=[]))


def _base_state() -> dict[str, Any]:
    return {
        "user_message": "什么是保证收益？",
        "customer_id": "CUST1",
        "conversation_id": "conv-1",
    }


def _faq_then_final(answer: str):
    """先调用 faq_search，再给出最终答复的脚本化模型。"""
    return make_fake_tool_model([
        tool_call("faq_search", {"query": "保证收益"}),
        final_message(answer),
    ])


# test_conversation_graph_rejects_non_whitelisted_tool 已删除：白名单执行器机制
# 随重构移除——``create_agent`` 只挂载 ``faq_search``，不存在可被调用的非白名单工具。


def test_conversation_answers_with_faq_evidence():
    result = run_conversation(
        _found_retriever(), _faq_then_final(f"根据 FAQ：{_FAQ_ANSWER}"),
        user_message="什么是保证收益？",
    )

    assert "保证收益" in result["final_response"]
    assert result["tool_trace"] == ["faq_search"]
    assert result["status"] == "success"
    assert result["cited_faq"] is True


def test_conversation_graph_marks_faq_citations_as_trusted():
    """引用到 FAQ 原文时结果需标记为受信内容，供合规出口只审计不改写。"""
    graph = build_conversation_graph(
        _found_retriever(), _faq_then_final(f"根据 FAQ：{_FAQ_ANSWER}")
    )

    result = graph.invoke(_base_state())

    assert "保证收益" in result["final_response"]
    assert result["cited_faq"] is True


def test_conversation_no_match_discloses_no_reliable_answer():
    result = run_conversation(
        _not_found_retriever(), _faq_then_final(_NO_ANSWER),
        user_message="什么是保证收益？",
    )

    assert "没有可靠" in result["final_response"]
    assert result["cited_faq"] is False


def test_conversation_without_faq_hit_is_not_trusted():
    graph = build_conversation_graph(_not_found_retriever(), _faq_then_final(_NO_ANSWER))

    result = graph.invoke(_base_state())

    assert result["cited_faq"] is False


class _BoomModel:
    """模拟模型不可用（网络/鉴权失败等）。"""

    def _fail(self, *args: Any, **kwargs: Any) -> Any:
        raise ModuleNotFoundError("No module named 'sentence_transformers'")

    bind_tools = _fail
    bind = _fail
    invoke = _fail
    stream = _fail
    _generate = _fail


def test_conversation_model_failure_returns_refusal_and_reason_code():
    """模型不可用时给出可诊断的原因码，而不是让它冒泡成整轮崩溃。"""
    result = run_conversation(_not_found_retriever(), _BoomModel(), user_message="你好")

    assert result["status"] == "failed"
    assert result["final_response"] == CONVERSATION_REFUSAL
    assert any(
        w.startswith("conversation_failed:model_unavailable") for w in result["warnings"]
    ), result["warnings"]
    assert result["cited_faq"] is False


def test_conversation_failure_reason_does_not_leak_exception_text():
    """原因码只含错误类别与异常类型名，不得回显异常原文（message）。"""
    result = run_conversation(_not_found_retriever(), _BoomModel(), user_message="你好")

    joined = " ".join(result["warnings"])
    assert "sentence_transformers" not in joined
    # 格式固定为 conversation_failed:<cause>:<ExcType>，不包含异常 message。
    assert joined == "conversation_failed:model_unavailable:ModuleNotFoundError"


def test_conversation_step_limit_yields_partial_with_warning():
    """模型每轮都请求工具时由步数上限截断，诚实降级为 partial（不伪报成功）。"""
    model = make_fake_tool_model([
        tool_call("faq_search", {"query": "x"}, call_id=f"c{i}") for i in range(4)
    ])

    result = run_conversation(
        _not_found_retriever(), model, user_message="随便问问", max_steps=1
    )

    assert result["status"] == "partial"
    assert "conversation_step_limit" in result["warnings"]


def test_faq_tool_returns_reviewed_answer_intact_with_blank_lines():
    """答案内部可以有空行；工具输出必须完整使用 answer，不能按字符串格式猜测。"""
    import json

    answer = "任何声称保证收益的宣传都涉嫌违规。\n\n投资者应核实产品材料。"
    retriever = _found_retriever()
    retriever._result.matches[0].answer = answer

    payload = json.loads(build_faq_tool(retriever).invoke({"query": "保证收益"}))

    assert payload["status"] == "found"
    assert payload["answer"] == answer


# ── 能力自述：必须覆盖四个业务领域 ────────────────────────────────


def _capturing_model(captured: list[list[Any]]) -> Any:
    """记录每轮模型看到的完整消息（含 system 提示词），并直接给出终答。"""
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    class _Capturing(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):  # type: ignore[no-untyped-def]
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[no-untyped-def]
            captured.append(list(messages))
            return ChatResult(
                generations=[ChatGeneration(message=AIMessage(content="我可以帮你做以下事情。"))]
            )

    return _Capturing(messages=iter([]))


def test_conversation_prompt_declares_all_four_business_domains():
    """“你能做什么”必须如实覆盖四个业务领域。

    回归：早前提示词只描述"闲聊 + 投资规则 FAQ"，而这四个领域由 Root Graph 按意图
    路由到各自子图、不在会话节点执行，因此本节点看不到它们。结果是系统自称只会聊
    天与 FAQ（实测即如此），用户据此不再提出本可执行的问题。
    """
    captured: list[list[Any]] = []
    graph = build_conversation_graph(_not_found_retriever(), _capturing_model(captured))

    graph.invoke({"user_message": "你好，你能做什么？", "customer_id": "CUST1",
                  "conversation_id": "conv-1"})

    assert captured, "模型未收到任何消息"
    from langchain_core.messages import SystemMessage

    system_prompts = [m.content for m in captured[0] if isinstance(m, SystemMessage)]
    assert system_prompts, "system 提示词未被传入"
    prompt = str(system_prompts[0])
    # 四个业务领域各自的关键词都要出现。
    for keyword in ("个股", "大盘", "基金", "账户"):
        assert keyword in prompt, f"能力自述缺少「{keyword}」"
    # 账户领域只读、下单充值走页面这一约束必须保留，避免暗示对话可代客交易。
    assert "只读" in prompt
    # 能力自述本身不得削弱原有的合规约束。
    assert "不得编造" in prompt or "不构成投资建议" in prompt


def test_conversation_prompt_does_not_expose_internal_routing():
    """能力自述面向用户，不得暴露内部实现（"自动路由""指定模块"等）。

    回归：提示词曾指示模型说"这些问题直接问就行，系统会自动路由，不用指定模块"——
    把内部编排机制讲给用户，像是"在跟一套系统对话"。用户只要知道"直接提问即可"。
    """
    for leaked in ("自动路由", "指定模块", "无需指定", "不用指定", "模块"):
        assert leaked not in _CONVERSATION_PROMPT, f"能力自述泄露内部术语：{leaked}"
    # 传达同样的含义（不用挑能力）但用面向用户的说法。
    assert "直接提问" in _CONVERSATION_PROMPT
