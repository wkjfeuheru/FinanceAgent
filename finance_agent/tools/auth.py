"""SQLite-backed user registration, authentication and session management."""
from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time
from datetime import datetime
from typing import Any

from finance_agent.core.database import SQLiteStore, get_database

TOKEN_TTL_SECONDS = 7 * 24 * 3600


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()


class UserStore:
    def __init__(self, database: SQLiteStore | None = None):
        self.database = database or get_database()

    def register(self, username: str, password: str, display_name: str = "") -> dict[str, Any]:
        username = (username or "").strip()
        if len(username) < 2:
            raise ValueError("用户名至少需要 2 个字符")
        if len(password) < 6:
            raise ValueError("密码至少需要 6 个字符")
        salt = secrets.token_hex(16)
        name = display_name.strip() or username
        try:
            with self.database.connect() as db:
                cursor = db.execute(
                    "INSERT INTO users (customer_id, username, display_name, password_hash, salt, created_at) VALUES (NULL, ?, ?, ?, ?, ?)",
                    (username, name, _hash_password(password, salt), salt, datetime.now().isoformat(timespec="seconds")),
                )
                customer_id = f"CUST{cursor.lastrowid:06d}"
                db.execute("UPDATE users SET customer_id = ? WHERE id = ?", (customer_id, cursor.lastrowid))
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"用户名 {username} 已存在") from exc
        return {"customer_id": customer_id, "username": username, "display_name": name}

    def login(self, username: str, password: str) -> dict[str, Any]:
        with self.database.connect() as db:
            row = db.execute("SELECT * FROM users WHERE username = ? COLLATE NOCASE", ((username or "").strip(),)).fetchone()
            if row is None or not secrets.compare_digest(_hash_password(password, row["salt"]), row["password_hash"]):
                raise ValueError("用户名或密码错误")
            token = secrets.token_urlsafe(32)
            db.execute("DELETE FROM sessions WHERE expires_at <= ?", (int(time.time()),))
            db.execute("INSERT INTO sessions VALUES (?, ?, ?)", (token, row["customer_id"], int(time.time()) + TOKEN_TTL_SECONDS))
        return {"customer_id": row["customer_id"], "username": row["username"], "display_name": row["display_name"], "token": token}

    def verify_token(self, token: str) -> str | None:
        if not token:
            return None
        with self.database.connect() as db:
            row = db.execute("SELECT customer_id FROM sessions WHERE token = ? AND expires_at > ?", (token, int(time.time()))).fetchone()
            if row is None:
                db.execute("DELETE FROM sessions WHERE token = ?", (token,))
        return str(row["customer_id"]) if row else None

    def logout(self, token: str) -> bool:
        if not token:
            return False
        with self.database.connect() as db:
            return db.execute("DELETE FROM sessions WHERE token = ?", (token,)).rowcount > 0

    @staticmethod
    def _public(row: sqlite3.Row) -> dict[str, Any]:
        return {key: row[key] for key in ("username", "customer_id", "display_name", "created_at")}

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        with self.database.connect() as db:
            row = db.execute("SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)).fetchone()
        return self._public(row) if row else None

    def get_user_by_customer_id(self, customer_id: str) -> dict[str, Any] | None:
        with self.database.connect() as db:
            row = db.execute("SELECT * FROM users WHERE customer_id = ?", (customer_id.upper(),)).fetchone()
        return self._public(row) if row else None

    def delete_user(self, customer_id: str) -> bool:
        with self.database.connect() as db:
            conversation_ids = db.execute(
                "SELECT conversation_id FROM conversations WHERE customer_id = ?",
                (customer_id.upper(),),
            ).fetchall()
            for row in conversation_ids:
                db.execute("DELETE FROM conversation_messages WHERE conversation_id = ?", (row[0],))
            db.execute("DELETE FROM conversations WHERE customer_id = ?", (customer_id.upper(),))
            db.execute("DELETE FROM user_profiles WHERE customer_id = ?", (customer_id.upper(),))
            return db.execute("DELETE FROM users WHERE customer_id = ?", (customer_id.upper(),)).rowcount > 0


_user_store: UserStore | None = None


def get_user_store() -> UserStore:
    global _user_store
    if _user_store is None:
        _user_store = UserStore()
    return _user_store
