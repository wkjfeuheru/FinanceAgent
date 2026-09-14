"""旧 checkpoint 向带客户隔离线程键迁移的契约。"""

from __future__ import annotations

from finance_agent.data.postgres_stores import load_checkpoint_with_legacy_fallback
from finance_agent.orchestrator.run_state import RunStateStore
from finance_agent.orchestrator.thread_key import build_thread_id


class _FakeCheckpointSaver:
    def __init__(self) -> None:
        self.checkpoints: dict[str, dict] = {}
        self.requested_thread_ids: list[str] = []

    def get(self, config: dict) -> dict | None:
        thread_id = config["configurable"]["thread_id"]
        self.requested_thread_ids.append(thread_id)
        return self.checkpoints.get(thread_id)

    def put(self, config: dict, checkpoint: dict, metadata: dict, new_versions: dict) -> dict:
        del metadata, new_versions
        self.checkpoints[config["configurable"]["thread_id"]] = checkpoint
        return config


class _FakeBusinessStore:
    def __init__(self, owner_by_conversation: dict[str, str]) -> None:
        self._owner_by_conversation = owner_by_conversation
        self.ownership_checks: list[tuple[str, str]] = []

    def get_conversation(self, conversation_id: str, customer_id: str) -> dict | None:
        self.ownership_checks.append((conversation_id, customer_id))
        if self._owner_by_conversation.get(conversation_id) == customer_id:
            return {"conversation_id": conversation_id, "customer_id": customer_id}
        return None


class _MigrationStore:
    def __init__(self, owner_by_conversation: dict[str, str]) -> None:
        self.checkpointer = _FakeCheckpointSaver()
        self.business_store = _FakeBusinessStore(owner_by_conversation)

    def put_legacy(self, conversation_id: str, checkpoint: dict) -> None:
        self.checkpointer.checkpoints[conversation_id] = checkpoint

    def load(self, customer_id: str, conversation_id: str) -> dict | None:
        return load_checkpoint_with_legacy_fallback(
            customer_id,
            conversation_id,
            checkpointer=self.checkpointer,
            business_store=self.business_store,
        )


def test_legacy_checkpoint_is_only_read_for_the_owner():
    """防止猜到旧 conversation_id 的其他客户读取遗留状态。"""
    fake_store = _MigrationStore({"conv-1": "CUST1"})
    fake_store.put_legacy("conv-1", {"customer_id": "CUST1", "channel_versions": {}})

    assert fake_store.load("CUST1", "conv-1") is not None
    assert fake_store.load("CUST2", "conv-1") is None
    assert fake_store.checkpointer.checkpoints[build_thread_id("CUST1", "conv-1")]["customer_id"] == "CUST1"
    assert fake_store.checkpointer.requested_thread_ids == [
        "v1:CUST1:conv-1", "conv-1", "v1:CUST2:conv-1",
    ]


def test_new_customer_scoped_checkpoint_is_preferred_without_legacy_read():
    """防止旧键覆盖已经隔离的新 checkpoint。"""
    fake_store = _MigrationStore({"conv-1": "CUST1"})
    fake_store.put_legacy("conv-1", {"state": "legacy"})
    fake_store.checkpointer.checkpoints[build_thread_id("CUST1", "conv-1")] = {"state": "new"}

    assert fake_store.load("CUST1", "conv-1") == {"state": "new"}
    assert fake_store.checkpointer.requested_thread_ids == ["v1:CUST1:conv-1"]
    assert fake_store.business_store.ownership_checks == []


class _DeletingCheckpointSaver(_FakeCheckpointSaver):
    def __init__(self) -> None:
        super().__init__()
        self.deleted_thread_ids: list[str] = []

    def delete_thread(self, thread_id: str) -> None:
        self.deleted_thread_ids.append(thread_id)


def test_run_state_store_exposes_scoped_key_and_delegates_delete():
    """RunStateStore 必须只按复合键读写和删除。"""
    checkpointer = _DeletingCheckpointSaver()
    store = RunStateStore(
        checkpointer=checkpointer,
        business_store=_FakeBusinessStore({"conv-1": "CUST1"}),
    )

    assert store.thread_id("cust1", "conv-1") == "v1:CUST1:conv-1"
    assert store.checkpoint_config("cust1", "conv-1") == {
        "configurable": {"thread_id": "v1:CUST1:conv-1"},
    }
    assert store.delete("cust1", "conv-1") is True
    assert checkpointer.deleted_thread_ids == ["v1:CUST1:conv-1"]
    assert store.parse("v1:CUST1:conv-1") == ("CUST1", "conv-1")
