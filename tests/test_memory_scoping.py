"""Redis 记忆键必须按 customer 隔离，避免仅凭 conversation_id 越权读写。"""

from __future__ import annotations

from finance_agent.orchestrator.memory import RedisMemoryStore


class _FakeRedis:
    """最小 Redis 替身：只记录键与值，供键格式断言使用。"""

    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}
        self.values: dict[str, str] = {}
        self.deleted: list[tuple] = []
        self.expirations: dict[str, int] = {}

    def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)
        return len(self.lists[key])

    def ltrim(self, key, start, end):
        return True

    def expire(self, key, ttl):
        self.expirations[key] = ttl
        return True

    def lrange(self, key, start, end):
        values = self.lists.get(key, [])
        return values[start:] if start < 0 else values[start:end]

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, ex=None):
        self.values[key] = value
        return True

    def delete(self, *keys):
        for key in keys:
            self.deleted.append(key)
            self.lists.pop(key, None)
            self.values.pop(key, None)
        return len(keys)


def _store(client: _FakeRedis) -> RedisMemoryStore:
    store = RedisMemoryStore(redis_url="redis://localhost:6379/0")
    store._client = client
    return store


def test_window_and_summary_keys_include_customer_id():
    client = _FakeRedis()
    store = _store(client)

    store.append_window_message("cust1", "conv-1", "user", "你好")
    store.set_summary("cust1", "conv-1", "摘要")

    assert "finance_cs:conv:CUST1:conv-1:window" in client.lists
    assert "finance_cs:conv:CUST1:conv-1:summary" in client.values


def test_same_conversation_id_is_isolated_between_customers():
    client = _FakeRedis()
    store = _store(client)

    store.append_window_message("cust1", "shared", "user", "甲的私有消息")
    store.append_window_message("cust2", "shared", "user", "乙的私有消息")

    assert store.get_window_messages("cust1", "shared", 5)[0]["content"] == "甲的私有消息"
    assert store.get_window_messages("cust2", "shared", 5)[0]["content"] == "乙的私有消息"


def test_clear_conversation_only_deletes_its_own_customer_keys():
    client = _FakeRedis()
    store = _store(client)
    store.append_window_message("cust1", "conv-1", "user", "a")
    store.append_window_message("cust2", "conv-1", "user", "b")
    store.set_summary("cust1", "conv-1", "s1")
    store.set_summary("cust2", "conv-1", "s2")

    store.clear_conversation("cust1", "conv-1")

    assert "finance_cs:conv:CUST1:conv-1:window" in client.deleted
    assert "finance_cs:conv:CUST1:conv-1:summary" in client.deleted
    # 另一客户的同 id 会话不受影响。
    assert store.get_window_messages("cust2", "conv-1", 5)[0]["content"] == "b"
    assert store.get_summary("cust2", "conv-1") == "s2"


def test_customer_id_is_upper_cased_in_keys():
    client = _FakeRedis()
    store = _store(client)

    store.append_window_message("cust1", "conv-1", "user", "x")
    store.set_summary("cust1", "conv-1", "s")

    assert any(key.startswith("finance_cs:conv:CUST1:") for key in client.lists)
    assert any(key.startswith("finance_cs:conv:CUST1:") for key in client.values)
