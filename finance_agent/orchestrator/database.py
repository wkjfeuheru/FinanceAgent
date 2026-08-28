"""关系型数据库持久化层。

对话管理（conversations + messages）和用户画像（user_profiles）均存储于此。
用户认证（users + sessions）已迁移至 finance_agent/tools/auth.py 的内置 AuthDB。
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from finance_agent.config import SQLITE_PATH


class SQLiteStore:
    """关系型数据库持久化存储。对话、用户画像均存储于此。"""

    def __init__(self, path: str = SQLITE_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS user_profiles (
                    customer_id TEXT PRIMARY KEY,
                    risk_preference TEXT NOT NULL DEFAULT '',
                    budget_amount REAL NOT NULL DEFAULT 0,
                    stock_codes TEXT NOT NULL DEFAULT '[]',
                    holding_period TEXT NOT NULL DEFAULT '',
                    investment_goal TEXT NOT NULL DEFAULT '',
                    confirmed_facts TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    customer_id TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '新对话',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_conversations_customer
                    ON conversations(customer_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_messages_conversation
                    ON conversation_messages(conversation_id, id);
                """
            )

    def get_profile(self, customer_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM user_profiles WHERE customer_id = ?",
                (customer_id.upper(),),
            ).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["stock_codes"] = json.loads(data["stock_codes"] or "[]")
        data["confirmed_facts"] = json.loads(data["confirmed_facts"] or "{}")
        return data

    def save_profile(self, data: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute(
                """INSERT INTO user_profiles
                   (customer_id, risk_preference, budget_amount, stock_codes,
                    holding_period, investment_goal, confirmed_facts, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(customer_id) DO UPDATE SET
                     risk_preference=excluded.risk_preference,
                     budget_amount=excluded.budget_amount,
                     stock_codes=excluded.stock_codes,
                     holding_period=excluded.holding_period,
                     investment_goal=excluded.investment_goal,
                     confirmed_facts=excluded.confirmed_facts,
                     updated_at=excluded.updated_at""",
                (
                    str(data["customer_id"]).upper(), data.get("risk_preference", ""),
                    float(data.get("budget_amount", 0) or 0),
                    json.dumps(data.get("stock_codes", []), ensure_ascii=False),
                    data.get("holding_period", ""), data.get("investment_goal", ""),
                    json.dumps(data.get("confirmed_facts", {}), ensure_ascii=False),
                    data.get("updated_at", ""),
                ),
            )

    def delete_profiles(self, customer_id: str | None = None) -> int:
        with self.connect() as db:
            if customer_id:
                cursor = db.execute(
                    "DELETE FROM user_profiles WHERE customer_id = ?",
                    (customer_id.upper(),),
                )
            else:
                cursor = db.execute("DELETE FROM user_profiles")
            return cursor.rowcount

    def create_conversation(self, customer_id: str, title: str = "新对话",
                            conversation_id: str | None = None) -> dict[str, Any]:
        conversation_id = conversation_id or uuid.uuid4().hex
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as db:
            db.execute(
                "INSERT INTO conversations VALUES (?, ?, ?, ?, ?)",
                (conversation_id, customer_id.upper(), title.strip() or "新对话", now, now),
            )
        return {"conversation_id": conversation_id, "customer_id": customer_id.upper(),
                "title": title.strip() or "新对话", "created_at": now, "updated_at": now}

    def list_conversations(self, customer_id: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """SELECT c.*, COUNT(m.id) AS message_count
                   FROM conversations c LEFT JOIN conversation_messages m
                     ON m.conversation_id = c.conversation_id
                   WHERE c.customer_id = ? GROUP BY c.conversation_id
                   ORDER BY c.updated_at DESC""",
                (customer_id.upper(),),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_conversation(self, conversation_id: str, customer_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM conversations WHERE conversation_id = ? AND customer_id = ?",
                (conversation_id, customer_id.upper()),
            ).fetchone()
        return dict(row) if row else None

    def append_conversation_message(
        self, conversation_id: str, role: str, content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as db:
            db.execute(
                "INSERT INTO conversation_messages (conversation_id, role, content, metadata, timestamp) VALUES (?, ?, ?, ?, ?)",
                (conversation_id, role, content, json.dumps(metadata or {}, ensure_ascii=False), now),
            )
            db.execute("UPDATE conversations SET updated_at = ? WHERE conversation_id = ?", (now, conversation_id))

    def get_conversation_messages(self, conversation_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """SELECT role, content, metadata, timestamp FROM
                   (SELECT * FROM conversation_messages WHERE conversation_id = ? ORDER BY id DESC LIMIT ?)
                   ORDER BY id ASC""",
                (conversation_id, max(1, min(limit, 500))),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["metadata"] = json.loads(item["metadata"] or "{}")
            result.append(item)
        return result

    def rename_conversation_from_message(self, conversation_id: str, message: str) -> None:
        title = " ".join(message.strip().split())[:28] or "新对话"
        with self.connect() as db:
            db.execute(
                "UPDATE conversations SET title = ? WHERE conversation_id = ? AND title = '新对话'",
                (title, conversation_id),
            )

    def delete_conversation(self, conversation_id: str, customer_id: str) -> bool:
        with self.connect() as db:
            cursor = db.execute(
                "DELETE FROM conversations WHERE conversation_id = ? AND customer_id = ?",
                (conversation_id, customer_id.upper()),
            )
            return cursor.rowcount > 0


_database: SQLiteStore | None = None


def get_database() -> SQLiteStore:
    global _database
    if _database is None:
        _database = SQLiteStore()
    return _database
