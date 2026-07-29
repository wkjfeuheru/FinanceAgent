from finance_agent.core.memory import AgentMemoryContext, RedisMemoryStore


class FakeRedis:
    def __init__(self):
        self.expirations = []
        self.set_calls = []

    def rpush(self, key, value):
        return 1

    def ltrim(self, key, start, end):
        return True

    def delete(self, *keys):
        return len(keys)

    def expire(self, key, seconds):
        self.expirations.append((key, seconds))
        return True

    def set(self, key, value, **kwargs):
        self.set_calls.append((key, value, kwargs))
        return True


def make_store(ttl_seconds=3600):
    store = RedisMemoryStore(ttl_seconds=ttl_seconds)
    store._client = FakeRedis()
    return store


def test_window_expiration_is_refreshed_on_each_update():
    store = make_store()

    assert store.append_window_message("conv1", "user", "first") is True
    assert store.append_window_message("conv1", "assistant", "second") is True
    assert store._client.expirations == [
        ("finance_cs:conv:conv1:window", 3600),
        ("finance_cs:conv:conv1:window", 3600),
    ]


def test_replacing_window_sets_expiration_when_messages_exist():
    store = make_store()

    assert store.set_window_messages(
        "conv1", [{"role": "user", "content": "hello"}]
    ) is True
    assert store._client.expirations == [("finance_cs:conv:conv1:window", 3600)]


def test_summary_uses_atomic_one_hour_expiration():
    store = make_store()

    assert store.set_summary("conv1", "summary") is True
    assert store._client.set_calls == [
        ("finance_cs:conv:conv1:summary", "summary", {"ex": 3600})
    ]


def test_intent_context_uses_latest_six_messages_without_profile():
    memory = AgentMemoryContext(store=make_store())
    messages = [
        {"role": "user", "content": f"第{i}条 " + ("内容" * 120)}
        for i in range(8)
    ]

    context = memory.build_intent_context(messages)

    assert "第0条" not in context
    assert "第1条" not in context
    assert "第2条" in context
    assert "第7条" in context
    assert "风险偏好" not in context
    assert len(context) <= 1500
    assert all(len(line.split(": ", 1)[-1]) <= 180 for line in context.splitlines())


def test_load_context_preserves_six_fallback_messages_for_intent_summary():
    class EmptyStore:
        def get_summary(self, _conversation_id):
            return ""

        def get_window_messages(self, _conversation_id, _window_size):
            return []

    memory = AgentMemoryContext(store=EmptyStore())
    fallback = [
        {"role": "user", "content": f"第{i}条"}
        for i in range(8)
    ]

    loaded = memory.load_context("CUST001", "conv", fallback)

    assert memory.window_size == 6
    assert [item["content"] for item in loaded["sliding_window"]] == [
        "第2条", "第3条", "第4条", "第5条", "第6条", "第7条",
    ]
