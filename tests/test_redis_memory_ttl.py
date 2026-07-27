from finance_agent.core.memory import RedisMemoryStore


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


def test_legacy_messages_expire_after_one_hour():
    store = make_store()

    assert store.append_message("cust1", "user", "hello") is True
    assert store._client.expirations == [("finance_cs:CUST1:messages", 3600)]


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
