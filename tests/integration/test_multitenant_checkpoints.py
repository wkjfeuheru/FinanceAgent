"""多用户/多会话 checkpoint 隔离：相同 conversation_id 不共享状态。"""

from __future__ import annotations

from finance_agent.infrastructure.checkpoint.run_state import RunStateStore
from finance_agent.orchestration.runtime.thread_key import build_thread_id, parse_thread_id


class _FakeCheckpointer:
    def __init__(self) -> None:
        self.store: dict[str, dict] = {}
        self.deleted: list[str] = []

    def get(self, config: dict):
        return self.store.get(config["configurable"]["thread_id"])

    def put(self, config, checkpoint, metadata, new_versions):
        del metadata, new_versions
        self.store[config["configurable"]["thread_id"]] = checkpoint
        return config

    def delete_thread(self, thread_id: str) -> None:
        self.deleted.append(thread_id)


class _FakeBusinessStore:
    def __init__(self) -> None:
        self.owned: dict[str, str] = {}

    def get_conversation(self, conversation_id: str, customer_id: str):
        if self.owned.get(conversation_id) == customer_id:
            return {"conversation_id": conversation_id}
        return None


def test_same_conversation_id_isolated_by_customer():
    assert build_thread_id("CUST1", "same") != build_thread_id("CUST2", "same")
    assert build_thread_id("cust1", "same") == build_thread_id("CUST1", "same")


def test_scoped_checkpoints_do_not_leak_across_customers():
    checkpointer = _FakeCheckpointer()
    store = RunStateStore(checkpointer=checkpointer, business_store=_FakeBusinessStore())
    checkpointer.put(store.checkpoint_config("CUST1", "conv-1"), {"owner": "CUST1"}, {}, {})

    assert store.load("CUST1", "conv-1") == {"owner": "CUST1"}
    # 另一个客户读取同一 conversation_id 不得命中。
    assert store.load("CUST2", "conv-1") is None


def test_parse_rejects_legacy_key_without_version():
    import pytest

    with pytest.raises(ValueError):
        parse_thread_id("conv-1")
