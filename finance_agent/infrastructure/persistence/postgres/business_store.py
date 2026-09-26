"""画像、会话与消息的 PostgreSQL 适配器。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from finance_agent.infrastructure.persistence.postgres.connection import _PostgresBaseStore, _json_loads, _dict_rows

class PostgresBusinessStore(_PostgresBaseStore):
    """画像、会话、消息的 PostgreSQL 存储。"""

    def get_profile(self, customer_id: str) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "SELECT * FROM finance.user_profiles WHERE customer_id = %s",
                    (customer_id.upper(),),
                )
                row = cursor.fetchone()
                data = _dict_rows(cursor, [row])[0] if row else None
            finally:
                cursor.close()
        if data is None:
            return None
        data["stock_codes"] = _json_loads(data.get("stock_codes", []))
        data["confirmed_facts"] = _json_loads(data.get("confirmed_facts", {}))
        return data

    def save_profile(self, data: dict[str, Any]) -> None:
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """INSERT INTO finance.user_profiles
                       (customer_id, risk_preference, budget_amount, stock_codes,
                        holding_period, investment_goal, confirmed_facts, updated_at)
                       VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s::jsonb, %s)
                       ON CONFLICT (customer_id) DO UPDATE SET
                         risk_preference = EXCLUDED.risk_preference,
                         budget_amount = EXCLUDED.budget_amount,
                         stock_codes = EXCLUDED.stock_codes,
                         holding_period = EXCLUDED.holding_period,
                         investment_goal = EXCLUDED.investment_goal,
                         confirmed_facts = EXCLUDED.confirmed_facts,
                         updated_at = EXCLUDED.updated_at""",
                    (
                        str(data["customer_id"]).upper(),
                        data.get("risk_preference", ""),
                        float(data.get("budget_amount", 0) or 0),
                        json.dumps(data.get("stock_codes", []), ensure_ascii=False),
                        data.get("holding_period", ""),
                        data.get("investment_goal", ""),
                        json.dumps(data.get("confirmed_facts", {}), ensure_ascii=False),
                        data.get("updated_at", ""),
                    ),
                )
            finally:
                cursor.close()

    def delete_profiles(self, customer_id: str | None = None) -> int:
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                if customer_id:
                    cursor.execute(
                        "DELETE FROM finance.user_profiles WHERE customer_id = %s",
                        (customer_id.upper(),),
                    )
                else:
                    cursor.execute("DELETE FROM finance.user_profiles")
                count = cursor.rowcount
            finally:
                cursor.close()
        return count

    def create_conversation(self, customer_id: str, title: str = "新对话",
                            conversation_id: str | None = None) -> dict[str, Any]:
        self._ensure_schema()
        conversation_id = conversation_id or uuid.uuid4().hex
        now = datetime.now().isoformat(timespec="seconds")
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "INSERT INTO finance.conversations VALUES (%s, %s, %s, %s, %s)",
                    (conversation_id, customer_id.upper(), title.strip() or "新对话", now, now),
                )
            finally:
                cursor.close()
        return {"conversation_id": conversation_id, "customer_id": customer_id.upper(),
                "title": title.strip() or "新对话", "created_at": now, "updated_at": now}

    def list_conversations(self, customer_id: str) -> list[dict[str, Any]]:
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """SELECT c.*, COUNT(m.message_id) AS message_count
                       FROM finance.conversations c
                       LEFT JOIN finance.conversation_messages m
                         ON m.conversation_id = c.conversation_id
                       WHERE c.customer_id = %s
                       GROUP BY c.conversation_id
                       ORDER BY c.updated_at DESC""",
                    (customer_id.upper(),),
                )
                rows = cursor.fetchall()
                result = _dict_rows(cursor, rows)
            finally:
                cursor.close()
        return result

    def get_conversation(self, conversation_id: str, customer_id: str) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "SELECT * FROM finance.conversations WHERE conversation_id = %s AND customer_id = %s",
                    (conversation_id, customer_id.upper()),
                )
                row = cursor.fetchone()
                result = _dict_rows(cursor, [row])[0] if row else None
            finally:
                cursor.close()
        return result

    def append_conversation_message(
        self, conversation_id: str, role: str, content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._ensure_schema()
        now = datetime.now().isoformat(timespec="seconds")
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """INSERT INTO finance.conversation_messages
                       (message_id, conversation_id, role, content, metadata, created_at)
                       VALUES (%s, %s, %s, %s, %s::jsonb, %s)""",
                    (
                        str(uuid.uuid4()),
                        conversation_id,
                        role,
                        content,
                        json.dumps(metadata or {}, ensure_ascii=False),
                        now,
                    ),
                )
                cursor.execute(
                    "UPDATE finance.conversations SET updated_at = %s WHERE conversation_id = %s",
                    (now, conversation_id),
                )
            finally:
                cursor.close()

    def get_conversation_messages(self, conversation_id: str, limit: int = 100) -> list[dict[str, Any]]:
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """SELECT role, content, metadata, created_at AS timestamp FROM (
                           SELECT * FROM finance.conversation_messages
                           WHERE conversation_id = %s ORDER BY created_at DESC, message_id DESC LIMIT %s
                       ) t ORDER BY created_at ASC, message_id ASC""",
                    (conversation_id, max(1, min(limit, 500))),
                )
                rows = cursor.fetchall()
                result = _dict_rows(cursor, rows)
            finally:
                cursor.close()
        for item in result:
            item["metadata"] = _json_loads(item.get("metadata", {}))
        return result

    def get_customer_messages(self, customer_id: str, limit: int = 100) -> list[dict[str, Any]]:
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """SELECT role, content, metadata, created_at AS timestamp FROM (
                           SELECT m.* FROM finance.conversation_messages m
                           JOIN finance.conversations c ON m.conversation_id = c.conversation_id
                           WHERE c.customer_id = %s ORDER BY m.created_at DESC, m.message_id DESC LIMIT %s
                       ) t ORDER BY created_at ASC, message_id ASC""",
                    (customer_id.upper(), max(1, min(limit, 500))),
                )
                rows = cursor.fetchall()
                result = _dict_rows(cursor, rows)
            finally:
                cursor.close()
        for item in result:
            item["metadata"] = _json_loads(item.get("metadata", {}))
        return result

    def rename_conversation_from_message(self, conversation_id: str, message: str) -> None:
        self._ensure_schema()
        title = " ".join(message.strip().split())[:28] or "新对话"
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "UPDATE finance.conversations SET title = %s WHERE conversation_id = %s AND title = '新对话'",
                    (title, conversation_id),
                )
            finally:
                cursor.close()

    def delete_conversation(self, conversation_id: str, customer_id: str) -> bool:
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "DELETE FROM finance.conversations WHERE conversation_id = %s AND customer_id = %s",
                    (conversation_id, customer_id.upper()),
                )
                count = cursor.rowcount
            finally:
                cursor.close()
        return count > 0


def load_checkpoint_with_legacy_fallback(
    customer_id: str,
    conversation_id: str,
    *,
    checkpointer: Any,
    business_store: PostgresBusinessStore,
) -> Any:
    """读取客户隔离 checkpoint，并在确认会话归属后迁移旧键。

    委托给 ``RunStateStore``（设计 §6.9）；保留该模块级函数以兼容既有调用。
    """
    from finance_agent.infrastructure.checkpoint.run_state import RunStateStore

    return RunStateStore(
        checkpointer=checkpointer,
        business_store=business_store,
    ).load(customer_id, conversation_id)

