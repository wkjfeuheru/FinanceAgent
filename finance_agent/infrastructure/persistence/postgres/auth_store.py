"""认证用户与登录会话的 PostgreSQL 适配器。"""

from __future__ import annotations

import secrets
import time
from datetime import datetime
from typing import Any

from finance_agent.infrastructure.persistence.postgres.connection import (
    TOKEN_TTL_SECONDS,
    _PostgresBaseStore,
    _dict_rows,
    _hash_password,
)

PASSWORD_MAX_LENGTH = 64
WEAK_PASSWORDS = frozenset({
    "admin123", "123456", "12345678", "password", "admin", "changeme",
    "qwerty", "111111", "000000",
})


def _validate_password(password: str) -> None:
    """在认证存储边界统一拒绝过短、过长或常见弱口令。"""
    if len(password or "") < 6:
        raise ValueError("密码至少需要 6 个字符")
    if len(password) > PASSWORD_MAX_LENGTH:
        raise ValueError(f"密码不得超过 {PASSWORD_MAX_LENGTH} 个字符")
    if password.lower() in WEAK_PASSWORDS:
        raise ValueError("密码过于简单，请更换")

class PostgresAuthStore(_PostgresBaseStore):
    """认证（用户 + 会话）的 PostgreSQL 存储。"""

    def register(
        self, username: str, password: str, display_name: str = "", *, is_admin: bool = False,
    ) -> dict[str, Any]:
        """注册用户；``is_admin`` 仅由引导脚本使用（注册接口不暴露该参数）。"""
        username = (username or "").strip()
        if len(username) < 2:
            raise ValueError("用户名至少需要 2 个字符")
        _validate_password(password)
        salt = secrets.token_hex(16)
        name = display_name.strip() or username
        self._ensure_schema()
        try:
            with self._transaction() as connection:
                cursor = connection.cursor()
                try:
                    cursor.execute(
                        """INSERT INTO finance.users
                           (customer_id, username, display_name, password_hash, salt,
                            created_at, is_admin)
                           VALUES (NULL, %s, %s, %s, %s, %s, %s) RETURNING id""",
                        (username, name, _hash_password(password, salt), salt,
                         datetime.now().isoformat(timespec="seconds"), bool(is_admin)),
                    )
                    row = cursor.fetchone()
                    user_id = row[0]
                    customer_id = f"CUST{user_id:06d}"
                    cursor.execute(
                        "UPDATE finance.users SET customer_id = %s WHERE id = %s",
                        (customer_id, user_id),
                    )
                finally:
                    cursor.close()
        except Exception as exc:
            if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                raise ValueError(f"用户名 {username} 已存在") from exc
            raise
        return {"customer_id": customer_id, "username": username, "display_name": name,
                "is_admin": bool(is_admin)}

    def login(self, username: str, password: str) -> dict[str, Any]:
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "SELECT * FROM finance.users WHERE LOWER(username) = LOWER(%s)",
                    ((username or "").strip(),),
                )
                row = cursor.fetchone()
                user = _dict_rows(cursor, [row])[0] if row else None
            finally:
                cursor.close()
        if user is None or not secrets.compare_digest(_hash_password(password, user["salt"]), user["password_hash"]):
            raise ValueError("用户名或密码错误")
        token = secrets.token_urlsafe(32)
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "DELETE FROM finance.sessions WHERE expires_at <= %s",
                    (int(time.time()),),
                )
                cursor.execute(
                    "INSERT INTO finance.sessions VALUES (%s, %s, %s)",
                    (token, user["customer_id"], int(time.time()) + TOKEN_TTL_SECONDS),
                )
            finally:
                cursor.close()
        return {"customer_id": user["customer_id"], "username": user["username"],
                "display_name": user["display_name"], "token": token,
                "is_admin": bool(user.get("is_admin"))}

    def verify_token(self, token: str) -> str | None:
        if not token:
            return None
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "SELECT customer_id FROM finance.sessions WHERE token = %s AND expires_at > %s",
                    (token, int(time.time())),
                )
                row = cursor.fetchone()
                if row is None:
                    cursor.execute("DELETE FROM finance.sessions WHERE token = %s", (token,))
                customer_id = str(row[0]) if row else None
            finally:
                cursor.close()
        return customer_id

    def logout(self, token: str) -> bool:
        if not token:
            return False
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute("DELETE FROM finance.sessions WHERE token = %s", (token,))
                count = cursor.rowcount
            finally:
                cursor.close()
        return count > 0

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "SELECT * FROM finance.users WHERE LOWER(username) = LOWER(%s)",
                    ((username or "").strip(),),
                )
                row = cursor.fetchone()
                result = self._public(cursor, row) if row else None
            finally:
                cursor.close()
        return result

    def get_user_by_customer_id(self, customer_id: str) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "SELECT * FROM finance.users WHERE customer_id = %s",
                    (customer_id.upper(),),
                )
                row = cursor.fetchone()
                result = self._public(cursor, row) if row else None
            finally:
                cursor.close()
        return result

    def is_admin(self, customer_id: str) -> bool:
        """读取用户的库内管理员角色；用户不存在时返回 False。"""
        if not customer_id:
            return False
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "SELECT is_admin FROM finance.users WHERE customer_id = %s",
                    (customer_id.upper(),),
                )
                row = cursor.fetchone()
            finally:
                cursor.close()
        return bool(row[0]) if row else False

    def set_admin(self, customer_id: str, is_admin: bool) -> bool:
        """授予/撤销管理员角色，返回是否命中用户。"""
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "UPDATE finance.users SET is_admin = %s WHERE customer_id = %s",
                    (bool(is_admin), customer_id.upper()),
                )
                count = cursor.rowcount
            finally:
                cursor.close()
        return count > 0

    def set_password(self, customer_id: str, password: str) -> bool:
        """重置密码（重新生成盐），返回是否命中用户。

        与注册同用 PBKDF2-SHA256 + 随机盐；换密码必须换盐，否则同一个密码在
        两个账号上会得到相同的哈希。
        """
        _validate_password(password)
        self._ensure_schema()
        salt = secrets.token_hex(16)
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "UPDATE finance.users SET password_hash = %s, salt = %s WHERE customer_id = %s",
                    (_hash_password(password, salt), salt, customer_id.upper()),
                )
                count = cursor.rowcount
            finally:
                cursor.close()
        return count > 0

    def list_users(self) -> list[dict[str, Any]]:
        """全部用户及其账户概览，供管理后台展示。

        用 ``LEFT JOIN``：账户行是首次访问模拟交易时才惰性创建的，没有交易的
        用户并非异常，不能因为缺账户行就从列表里消失。
        """
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """SELECT u.id, u.customer_id, u.username, u.display_name, u.created_at,
                              u.is_admin,
                              COALESCE(a.cash_balance, 0) AS cash_balance,
                              COALESCE(a.total_deposit, 0) AS total_deposit,
                              COALESCE(p.position_count, 0) AS position_count
                       FROM finance.users u
                       LEFT JOIN finance.accounts a ON a.customer_id = u.customer_id
                       LEFT JOIN (
                           SELECT customer_id, COUNT(*) AS position_count
                           FROM finance.positions WHERE shares > 0 GROUP BY customer_id
                       ) p ON p.customer_id = u.customer_id
                       ORDER BY u.id""",
                )
                rows = cursor.fetchall()
                result = _dict_rows(cursor, rows)
            finally:
                cursor.close()
        for row in result:
            row["is_admin"] = bool(row.get("is_admin"))
        return result

    def delete_user(self, customer_id: str) -> bool:
        """删除用户，并先清理其研究审计数据。

        ``research_runs`` 没有指向 ``users`` 的外键，且 ``research_runs.agent_run_id``
        → ``agent_runs`` 未声明级联，因此仅靠 ``users`` 的级联会因外键约束失败，
        导致"注销账号"对已产生研究记录的用户直接 500。这里按依赖顺序显式清理。
        """
        self._ensure_schema()
        cid = customer_id.upper()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """DELETE FROM finance.research_results WHERE research_run_id IN (
                           SELECT research_run_id FROM finance.research_runs
                           WHERE customer_id = %s
                              OR agent_run_id IN (
                                  SELECT run_id FROM finance.agent_runs WHERE customer_id = %s
                              )
                       )""",
                    (cid, cid),
                )
                cursor.execute(
                    """DELETE FROM finance.research_runs
                       WHERE customer_id = %s
                          OR agent_run_id IN (
                              SELECT run_id FROM finance.agent_runs WHERE customer_id = %s
                          )""",
                    (cid, cid),
                )
                cursor.execute(
                    "DELETE FROM finance.users WHERE customer_id = %s",
                    (cid,),
                )
                count = cursor.rowcount
            finally:
                cursor.close()
        return count > 0

    def _public(self, cursor: Any, row: Any) -> dict[str, Any]:
        data = _dict_rows(cursor, [row])[0]
        return {key: data[key] for key in ("username", "customer_id", "display_name", "created_at")} | {
            "is_admin": bool(data.get("is_admin")),
        }

