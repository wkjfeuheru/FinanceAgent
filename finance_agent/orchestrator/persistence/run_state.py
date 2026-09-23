"""Checkpointer 的线程键、恢复与删除边界（设计 §6.9 RunStateStore）。

业务子图不直接访问 checkpoint 表；所有读写都通过本 seam，并使用复合线程键
``v1:{customer_id}:{conversation_id}``。旧键只在确认会话归属后才被读取并
迁移到新键，避免猜到 conversation_id 的其他客户读取遗留状态。
"""

from __future__ import annotations

from typing import Any

from finance_agent.orchestrator.persistence.thread_key import build_thread_id, parse_thread_id


class RunStateStore:
    """封装 checkpoint 线程键、读取/迁移、恢复配置与删除。"""

    def __init__(self, *, checkpointer: Any, business_store: Any) -> None:
        self._checkpointer = checkpointer
        self._business_store = business_store

    def thread_id(self, customer_id: str, conversation_id: str) -> str:
        return build_thread_id(customer_id, conversation_id)

    def checkpoint_config(self, customer_id: str, conversation_id: str) -> dict[str, Any]:
        """返回复合键对应的 LangGraph 调用配置。"""
        return {"configurable": {"thread_id": self.thread_id(customer_id, conversation_id)}}

    def load(self, customer_id: str, conversation_id: str) -> Any:
        """读取客户隔离 checkpoint，并在确认归属后迁移旧键。"""
        thread_id = self.thread_id(customer_id, conversation_id)
        scoped_config = {"configurable": {"thread_id": thread_id}}
        checkpoint = self._checkpointer.get(scoped_config)
        if checkpoint is not None:
            return checkpoint

        if self._business_store.get_conversation(conversation_id, customer_id) is None:
            return None

        legacy_checkpoint = self._checkpointer.get({"configurable": {"thread_id": conversation_id}})
        if legacy_checkpoint is None:
            return None

        self._checkpointer.put(
            scoped_config,
            legacy_checkpoint,
            {},
            legacy_checkpoint.get("channel_versions", {}),
        )
        return legacy_checkpoint

    def delete(self, customer_id: str, conversation_id: str) -> bool:
        """删除复合键 checkpoint 及其写入记录，返回是否执行了删除。"""
        thread_id = self.thread_id(customer_id, conversation_id)
        checkpointer = self._checkpointer
        delete_thread = getattr(checkpointer, "delete_thread", None)
        if callable(delete_thread):
            delete_thread(thread_id)
            return True

        connection = getattr(checkpointer, "conn", None)
        if connection is None:
            return False
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM checkpoint_writes WHERE thread_id = %s", (thread_id,))
            cursor.execute("DELETE FROM checkpoints WHERE thread_id = %s", (thread_id,))
            connection.commit()
        return True

    @staticmethod
    def parse(thread_id: str) -> tuple[str, str]:
        return parse_thread_id(thread_id)
