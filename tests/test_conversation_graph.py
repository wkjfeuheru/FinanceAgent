"""会话子图：仅暴露 faq_search，非白名单工具被安全拒绝。"""

from __future__ import annotations

from typing import Any, Sequence

from finance_agent.faq.contracts import FaqSearchMatch, FaqSearchResult
from finance_agent.orchestrator.conversation_graph import build_conversation_graph


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
                    answer="任何声称“保证收益”的宣传都涉嫌违规。",
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


def _model_calling(tool_name: str) -> Any:
    def model(messages: Sequence[dict[str, Any]]) -> dict[str, Any]:
        if not any(message.get("role") == "observation" for message in messages):
            return {"action": "tool", "tool_name": tool_name, "tool_input": {"query": "保证收益"}}
        observation = next(m for m in messages if m.get("role") == "observation")
        return {"action": "final", "final_text": f"根据 FAQ：{observation['content']}"}

    return model


def test_conversation_graph_rejects_non_whitelisted_tool():
    graph = build_conversation_graph(_found_retriever(), _model_calling("stock_quote"))

    result = graph.invoke(_base_state())

    assert result["final_response"] == "暂时无法执行该操作。"
    assert result["status"] == "failed"


def test_conversation_graph_answers_with_faq_evidence():
    graph = build_conversation_graph(_found_retriever(), _model_calling("faq_search"))

    result = graph.invoke(_base_state())

    assert "保证收益" in result["final_response"]
    assert result["tool_trace"] == ["faq_search"]


def test_conversation_graph_no_match_observation_discloses_no_reliable_answer():
    graph = build_conversation_graph(_not_found_retriever(), _model_calling("faq_search"))

    result = graph.invoke(_base_state())

    assert result["observations"][0]["text"].find("没有可靠") != -1
    assert "没有可靠" in result["final_response"]


# ── 能力自述：必须覆盖四个业务领域 ────────────────────────────────

def _capturing_model(captured: list[str]) -> Any:
    """记录 system 提示词并直接给出终答，不触发工具调用。"""

    def model(messages: Sequence[dict[str, Any]]) -> dict[str, Any]:
        for message in messages:
            if message.get("role") == "system":
                captured.append(str(message.get("content", "")))
        return {"action": "final", "final_text": "我可以帮你做以下事情。"}

    return model


def test_conversation_prompt_declares_all_four_business_domains():
    """“你能做什么”必须如实覆盖四个业务领域。

    回归：早前提示词只描述"闲聊 + 投资规则 FAQ"，而这四个领域由 Root Graph 按意图
    路由到各自子图、不在会话节点执行，因此本节点看不到它们。结果是系统自称只会聊
    天与 FAQ（实测即如此），用户据此不再提出本可执行的问题。
    """
    captured: list[str] = []
    graph = build_conversation_graph(_not_found_retriever(), _capturing_model(captured))

    graph.invoke({"user_message": "你好，你能做什么？", "customer_id": "CUST1",
                  "conversation_id": "conv-1"})

    assert captured, "system 提示词未被传入"
    prompt = captured[0]
    # 四个业务领域各自的关键词都要出现。
    for keyword in ("个股", "大盘", "基金", "账户"):
        assert keyword in prompt, f"能力自述缺少「{keyword}」"
    # 账户领域只读、下单充值走页面这一约束必须保留，避免暗示对话可代客交易。
    assert "只读" in prompt
    # 能力自述本身不得削弱原有的合规约束。
    assert "不得编造" in prompt or "不构成投资建议" in prompt


class _BoomRetriever:
    """模拟 FAQ 工具不可用（如依赖缺失/模型加载失败）。"""

    def search(self, query, top_k=None):
        del query, top_k
        raise ModuleNotFoundError("No module named 'sentence_transformers'")


def test_conversation_failure_exposes_diagnosable_reason_code():
    """工具失败时必须给出可诊断的原因码，而不是只有笼统兜底文案。"""
    graph = build_conversation_graph(_BoomRetriever(), _model_calling("faq_search"))

    result = graph.invoke(_base_state())

    assert result["status"] == "failed"
    assert result["final_response"] == "暂时无法执行该操作。"
    assert any(w.startswith("conversation_failed:tool_failed:faq_search") for w in result["warnings"]), result["warnings"]


def test_conversation_failure_reason_does_not_leak_exception_text():
    """原因码只含错误类别与工具名，不得回显异常原文。"""
    graph = build_conversation_graph(_BoomRetriever(), _model_calling("faq_search"))

    result = graph.invoke(_base_state())

    joined = " ".join(result["warnings"])
    assert "sentence_transformers" not in joined
    assert "ModuleNotFoundError" not in joined


def test_conversation_marks_faq_citations_as_trusted():
    """引用到 FAQ 原文时，结果需标记为受信内容，供合规出口只审计不改写。"""
    graph = build_conversation_graph(_found_retriever(), _model_calling("faq_search"))

    result = graph.invoke(_base_state())

    assert result["cited_faq"] is True


def test_conversation_without_faq_hit_is_not_trusted():
    graph = build_conversation_graph(_not_found_retriever(), _model_calling("faq_search"))

    result = graph.invoke(_base_state())

    assert result["cited_faq"] is False


def test_rendered_observation_uses_explicit_answer_without_splitting():
    """答案内部可以有空行；渲染必须完整使用 answer，不能再按字符串格式猜测。"""
    from finance_agent.orchestrator.conversation_graph import _render_faq

    result = _found_retriever()._result
    result.matches[0].answer = "任何声称保证收益的宣传都涉嫌违规。\n\n投资者应核实产品材料。"

    text = _render_faq(result)

    assert text == "任何声称保证收益的宣传都涉嫌违规。\n\n投资者应核实产品材料。"
