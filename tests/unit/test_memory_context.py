"""会话工作记忆预算测试。"""

from finance_agent.orchestration.memory import AgentMemoryContext, UserProfileCard


class EmptyMemoryStore:
    def get_window_messages(self, customer_id, conversation_id, window_size):
        return [
            {"role": "user", "content": "最近消息 " * 20},
            {"role": "assistant", "content": "上一轮回复 " * 20},
        ]


def test_context_budget_keeps_task_facts_and_recent_messages():
    context = AgentMemoryContext(
        store=EmptyMemoryStore(),
        max_context_chars=1000,
        max_context_tokens=40,
    )
    context.get_profile = lambda customer_id: UserProfileCard(
        customer_id=customer_id, risk_preference="R2"
    )
    context.format_profile = lambda profile: "长期画像 " * 30

    loaded = context.load_context(
        "CUST001",
        "conversation-1",
        task_facts=[{"fact_id": "fact-quote", "payload": {"price": 100}}],
    )

    assert "fact-quote" in loaded["context_text"]
    assert "滑动窗口" in loaded["context_text"]
    assert len(loaded["context_text"]) <= 40 * 4
