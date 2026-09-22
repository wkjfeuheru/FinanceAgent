"""模型数据库与股票数据工具契约测试。"""

import json


def test_database_tools_are_langchain_tools_and_scope_conversation(monkeypatch):
    from finance_agent.orchestrator.tools import database

    class FakeDatabase:
        def get_profile(self, customer_id):
            return {"customer_id": customer_id, "risk_preference": "稳健"}

        def list_conversations(self, customer_id):
            return [{"conversation_id": "conv-1", "customer_id": customer_id}]

        def get_conversation(self, conversation_id, customer_id):
            if conversation_id == "conv-1" and customer_id == "user-1":
                return {"conversation_id": conversation_id, "customer_id": customer_id}
            return None

        def get_conversation_messages(self, conversation_id, limit):
            return [{"conversation_id": conversation_id, "content": "hello"}]

    monkeypatch.setattr(database, "get_database", lambda: FakeDatabase())

    profile = json.loads(database.query_user_profile.invoke({"customer_id": "user-1"}))
    assert profile["risk_preference"] == "稳健"

    messages = json.loads(database.get_user_conversation_messages.invoke({
        "customer_id": "user-1",
        "conversation_id": "conv-1",
    }))
    assert messages[0]["content"] == "hello"

    denied = json.loads(database.get_user_conversation_messages.invoke({
        "customer_id": "user-2",
        "conversation_id": "conv-1",
    }))
    assert denied["error"] == "会话不存在或无权访问"


def test_unified_stock_tool_facade_exports_existing_model_tools():
    from finance_agent.orchestrator.tools.stockdata import (
        get_stock_history,
        get_stock_quote,
        search_candidates,
    )

    assert get_stock_quote.name == "get_stock_quote"
    assert get_stock_history.name == "get_stock_history"
    assert search_candidates.name == "search_candidates"
