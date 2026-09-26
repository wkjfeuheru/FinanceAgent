"""产品工具与 SSE 链路测试。产品专家只做目录查询，不跑评估管线。"""

import asyncio
from uuid import uuid4

from finance_agent.api.sse import build_final_response_event
from finance_agent.shared.contracts import ExpertResult, ExpertStatus, ResponseEnvelope
from finance_agent.orchestration.contracts import BusinessDomain
from finance_agent.orchestration.experts.base import ExpertSink
from finance_agent.domains.products.expert.catalog import query_product
from finance_agent.application.advisor import AdvisorSystem


def test_query_product_without_data_is_empty_not_fabricated(monkeypatch):
    """产品库无记录时不得伪造产品字段。"""
    import finance_agent.domains.products.expert.catalog as catalog

    class _Empty:
        def query_by_code(self, code):
            return None

        def query_by_name(self, name):
            return None

    monkeypatch.setattr(catalog, "get_product_library", lambda: _Empty())

    sink = ExpertSink(domain=BusinessDomain.PRODUCT_RESEARCH, customer_id="CUST1")
    raw = query_product.invoke(
        {"product_code": "110011"},
        config={"configurable": {"expert_sink": sink}},
    )

    assert "error" in raw
    assert "product" not in sink.structured
    assert "product_not_found" in sink.limitations


def test_final_sse_event_keeps_legacy_response_shape():
    """最终 SSE 事件应携带完整且可 JSON 序列化的旧响应。"""
    event = build_final_response_event(ResponseEnvelope(
        run_id=uuid4(),
        trace_id=uuid4(),
        conversation_id="conversation-test",
        message_id=uuid4(),
        response="测试回复",
        results=[ExpertResult(
            expert_name="product_analysis",
            status=ExpertStatus.SUCCESS,
            summary="产品分析完成",
            result_data={"report": "产品报告"},
        )],
    ))

    assert event["type"] == "response"
    assert event["content"] == "测试回复"
    assert event["data"]["conversation_id"] == "conversation-test"
    assert event["data"]["product_analysis"] == {"report": "产品报告"}


def test_stream_emits_delta_chunks_before_final_response(monkeypatch):
    """定稿答复应先分块下发 delta，再以完整 response 收尾；拼接可还原全文。"""
    system = object.__new__(AdvisorSystem)

    def fake_handle(message, chat_history=None, customer_id="CUST001", progress_callback=None, conversation_id="", resume=False, answers=None):
        return {
            "response": "贵州茅台基本面稳健，估值处于合理区间。",
            "task_plan": ["stock_analysis"],
            "conversation_id": conversation_id or "generated",
        }

    monkeypatch.setattr(system, "handle_message", fake_handle)

    async def collect():
        return [
            item async for item in system.handle_message_stream(
                "分析贵州茅台", conversation_id="conversation-test",
            )
        ]

    events = asyncio.run(collect())
    deltas = [item for item in events if item.get("type") == "delta"]
    response_index = next(i for i, item in enumerate(events) if item.get("type") == "response")

    assert len(deltas) > 1, "长答复应被切成多块下发"
    assert "".join(item["content"] for item in deltas) == "贵州茅台基本面稳健，估值处于合理区间。"
    # 所有 delta 必须早于最终 response，前端才能先累积后定稿。
    assert all(i < response_index for i, item in enumerate(events) if item.get("type") == "delta")


def test_stream_emits_stages_and_final_response(monkeypatch):
    """SSE 包装层应输出阶段事件、最终响应及完整数据。"""
    system = object.__new__(AdvisorSystem)

    def fake_handle(message, chat_history=None, customer_id="CUST001", progress_callback=None, conversation_id="", resume=False, answers=None):
        if progress_callback:
            progress_callback("manager", "完成分派")
        return {
            "response": "测试回复",
            "task_plan": ["casual_chat"],
            "conversation_id": conversation_id or "generated",
        }

    monkeypatch.setattr(system, "handle_message", fake_handle)

    async def collect():
        return [
            item async for item in system.handle_message_stream(
                "你好", conversation_id="conversation-test",
            )
        ]

    events = asyncio.run(collect())

    assert events[0]["type"] == "stage"
    assert any(item.get("type") == "response" for item in events)
    response = next(item for item in events if item.get("type") == "response")
    assert response["content"] == "测试回复"
    assert response["data"]["task_plan"] == ["casual_chat"]
