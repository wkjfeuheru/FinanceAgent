"""Redis 故障时的业务事实恢复测试。"""

from finance_agent.orchestrator.memory import AgentMemoryContext, UserProfileCard


class UnavailableRedis:
    def is_available(self):
        return False

    def get_summary(self, conversation_id):
        raise AssertionError("Redis 不可用时不应读取摘要")

    def get_window_messages(self, conversation_id, window_size):
        raise AssertionError("Redis 不可用时不应读取窗口")


def test_redis_failure_recovers_messages_and_profile_from_business_store():
    context = AgentMemoryContext(
        store=UnavailableRedis(),
        profile_loader=lambda customer_id: {
            "customer_id": customer_id,
            "risk_preference": "R2 中低风险",
            "confirmed_facts": {"budget_amount": 100000},
        },
        messages_loader=lambda conversation_id, limit: [
            {"role": "user", "content": "恢复的业务消息"},
        ],
    )

    loaded = context.load_context("CUST001", "conversation-1")

    assert loaded["profile"]["risk_preference"] == "R2 中低风险"
    assert loaded["sliding_window"][0]["content"] == "恢复的业务消息"
    assert "恢复的业务消息" in loaded["context_text"]


def test_redis_failure_uses_explicit_fallback_messages_when_business_loader_missing():
    context = AgentMemoryContext(store=UnavailableRedis())
    context.get_profile = lambda customer_id: UserProfileCard(customer_id=customer_id)

    loaded = context.load_context(
        "CUST001",
        "conversation-1",
        fallback_messages=[{"role": "user", "content": "请求消息"}],
    )

    assert loaded["sliding_window"][0]["content"] == "请求消息"
