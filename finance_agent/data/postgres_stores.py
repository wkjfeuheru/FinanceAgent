"""PostgreSQL 业务存储层。

将原本 SQLite 承载的表（画像/会话/消息/认证/产品库）迁移到 PostgreSQL，
接口与既有 SQLite 实现保持一致，供 ``get_database`` / ``get_user_store`` /
``get_product_library`` 在配置 ``POSTGRES_DSN`` 时切换使用。
"""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

TOKEN_TTL_SECONDS = 7 * 24 * 3600
PASSWORD_MAX_LENGTH = 64
WEAK_PASSWORDS = frozenset({
    "admin123", "123456", "12345678", "password", "admin", "changeme",
    "qwerty", "111111", "000000",
})


def is_unique_violation(exc: BaseException) -> bool:
    """识别 PostgreSQL unique_violation（SQLSTATE 23505）及其包装异常。"""
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if str(getattr(current, "sqlstate", "") or "") == "23505":
            return True
        try:
            from psycopg.errors import UniqueViolation
            if isinstance(current, UniqueViolation):
                return True
        except ImportError:
            pass
        current = current.__cause__ or current.__context__
    text = str(exc).lower()
    return "duplicate" in text and "unique" in text


class UniqueConstraintError(Exception):
    """测试与适配层用来模拟 PostgreSQL unique_violation（SQLSTATE 23505）。"""

    sqlstate = "23505"


def _validate_password(password: str) -> None:
    if len(password or "") < 6:
        raise ValueError("密码至少需要 6 个字符")
    if len(password) > PASSWORD_MAX_LENGTH:
        raise ValueError(f"密码不得超过 {PASSWORD_MAX_LENGTH} 个字符")
    if password.lower() in WEAK_PASSWORDS:
        raise ValueError("密码过于简单，请更换")


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()


def _json_loads(value: Any) -> Any:
    """将 jsonb 返回的 dict/list 或 JSON 字符串统一为 Python 对象。"""
    if value is None or isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _dict_rows(cursor: Any, rows: list[Any]) -> list[dict[str, Any]]:
    """按 cursor.description 将元组行转换为 dict。"""
    columns = [desc[0] for desc in (cursor.description or [])]
    return [dict(zip(columns, row)) for row in rows]


class _PostgresBaseStore:
    """共享的事务/建表能力。"""

    def __init__(self, connection_factory):
        self._connection_factory = connection_factory
        self._schema_ready = False
        # 建表是懒加载且只应执行一次；不同会话现在可并发进入，无锁时
        # 两个线程可能同时跑 DDL，在 Postgres 目录表上竞争。
        self._schema_lock = threading.Lock()

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        connection = self._connection_factory()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            self._apply_schema()

    def _apply_schema(self) -> None:
        from finance_agent.data.postgres_schema import apply_postgres_schema

        # 懒建表是安全网；部署以 python -m finance_agent.migrate 为准。
        # 业务路径不强制 pgvector，避免无扩展的库连登录都起不来。
        with self._transaction() as connection:
            apply_postgres_schema(connection, include_faq=False, include_seed=False)
        self._schema_ready = True


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
    from finance_agent.orchestrator.persistence.run_state import RunStateStore

    return RunStateStore(
        checkpointer=checkpointer,
        business_store=business_store,
    ).load(customer_id, conversation_id)


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
        # 超长口令直接当失败，避免未校验的 PBKDF2 成为 DoS 面。
        if len(password or "") > PASSWORD_MAX_LENGTH:
            raise ValueError("用户名或密码错误")
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
        cid = customer_id.upper()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "UPDATE finance.users SET password_hash = %s, salt = %s WHERE customer_id = %s",
                    (_hash_password(password, salt), salt, cid),
                )
                count = cursor.rowcount
                # 换密后旧令牌一律失效，否则重置被盗账号后原会话仍可用。
                cursor.execute(
                    "DELETE FROM finance.sessions WHERE customer_id = %s",
                    (cid,),
                )
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


class PostgresPortfolioStore(_PostgresBaseStore):
    """模拟交易账户、流水、委托与持仓的 PostgreSQL 存储。

    只做数据读写与行锁，不含费率与盈亏口径 —— 那些属于
    ``finance_agent.portfolio.service``，保证 REST 与 Agent 走同一套计算。
    """

    def ensure_account(self, customer_id: str) -> dict[str, Any]:
        """确保账户行存在并返回之（幂等）。"""
        self._ensure_schema()
        cid = customer_id.upper()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """INSERT INTO finance.accounts (customer_id)
                       VALUES (%s) ON CONFLICT (customer_id) DO NOTHING""",
                    (cid,),
                )
                cursor.execute(
                    "SELECT * FROM finance.accounts WHERE customer_id = %s",
                    (cid,),
                )
                row = cursor.fetchone()
                result = _dict_rows(cursor, [row])[0]
            finally:
                cursor.close()
        return result

    def lock_account(self, cursor: Any, customer_id: str) -> dict[str, Any] | None:
        """在调用方事务内锁定账户行，返回其当前值。

        写操作必须经由此处加锁，否则并发下单会各自读到同一份余额造成超支。
        """
        cursor.execute(
            "SELECT * FROM finance.accounts WHERE customer_id = %s FOR UPDATE",
            (customer_id.upper(),),
        )
        row = cursor.fetchone()
        return _dict_rows(cursor, [row])[0] if row else None

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        """暴露事务上下文，供服务层把一次成交的多个写操作包成原子操作。"""
        self._ensure_schema()
        with self._transaction() as connection:
            yield connection

    def find_transaction_by_key(self, customer_id: str, idempotency_key: str) -> dict[str, Any] | None:
        """按幂等键查找已落地的资金流水。"""
        if not idempotency_key:
            return None
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """SELECT * FROM finance.cash_transactions
                       WHERE customer_id = %s AND idempotency_key = %s LIMIT 1""",
                    (customer_id.upper(), idempotency_key),
                )
                row = cursor.fetchone()
                result = _dict_rows(cursor, [row])[0] if row else None
            finally:
                cursor.close()
        return result

    def find_order_by_key(self, customer_id: str, idempotency_key: str) -> dict[str, Any] | None:
        """按幂等键查找已成交的委托。"""
        if not idempotency_key:
            return None
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """SELECT * FROM finance.orders
                       WHERE customer_id = %s AND idempotency_key = %s LIMIT 1""",
                    (customer_id.upper(), idempotency_key),
                )
                row = cursor.fetchone()
                result = _dict_rows(cursor, [row])[0] if row else None
            finally:
                cursor.close()
        return result

    def insert_transaction(self, cursor: Any, record: dict[str, Any]) -> dict[str, Any]:
        """在调用方事务内写入一条资金流水，并返回落库后的行。

        用 ``RETURNING`` 直接取回，避免提交后再按时间排序回查 —— 同一秒内的多条
        流水时间戳相同，回查可能取到别的行。
        """
        cursor.execute(
            """INSERT INTO finance.cash_transactions
               (txn_id, customer_id, kind, amount, balance_after, ref_id, note,
                idempotency_key, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
               RETURNING *""",
            (
                record["txn_id"],
                str(record["customer_id"]).upper(),
                record["kind"],
                record["amount"],
                record["balance_after"],
                record.get("ref_id", ""),
                record.get("note", ""),
                record.get("idempotency_key", ""),
            ),
        )
        return _dict_rows(cursor, [cursor.fetchone()])[0]

    def insert_order(self, cursor: Any, record: dict[str, Any]) -> dict[str, Any]:
        """在调用方事务内写入一条委托，并返回落库后的行。"""
        cursor.execute(
            """INSERT INTO finance.orders
               (order_id, customer_id, product_code, side, shares, price,
                gross_amount, fee, net_amount, realized_pnl, fee_limitations,
                idempotency_key, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, now())
               RETURNING *""",
            (
                record["order_id"],
                str(record["customer_id"]).upper(),
                record["product_code"],
                record["side"],
                record["shares"],
                record["price"],
                record["gross_amount"],
                record["fee"],
                record["net_amount"],
                record.get("realized_pnl"),
                json.dumps(record.get("fee_limitations", []), ensure_ascii=False),
                record.get("idempotency_key", ""),
            ),
        )
        return _dict_rows(cursor, [cursor.fetchone()])[0]

    def update_cash_balance(self, cursor: Any, customer_id: str, cash_balance: float) -> None:
        """在调用方事务内更新可用资金。"""
        cursor.execute(
            "UPDATE finance.accounts SET cash_balance = %s, updated_at = now() WHERE customer_id = %s",
            (cash_balance, customer_id.upper()),
        )

    def add_deposit(self, cursor: Any, customer_id: str, amount: float) -> None:
        """在调用方事务内累加累计充值额。"""
        cursor.execute(
            "UPDATE finance.accounts SET total_deposit = total_deposit + %s, updated_at = now() WHERE customer_id = %s",
            (amount, customer_id.upper()),
        )

    def get_position_row(self, cursor: Any, customer_id: str, product_code: str) -> dict[str, Any] | None:
        """在调用方事务内读取单笔持仓（加锁）。"""
        cursor.execute(
            """SELECT * FROM finance.positions
               WHERE customer_id = %s AND product_code = %s FOR UPDATE""",
            (customer_id.upper(), product_code),
        )
        row = cursor.fetchone()
        return _dict_rows(cursor, [row])[0] if row else None

    def upsert_position(
        self, cursor: Any, customer_id: str, product_code: str,
        shares: float, cost_amount: float,
    ) -> None:
        """在调用方事务内写入/更新持仓；份额归零时删除该行。"""
        cid = customer_id.upper()
        if shares <= 0:
            cursor.execute(
                "DELETE FROM finance.positions WHERE customer_id = %s AND product_code = %s",
                (cid, product_code),
            )
            return
        avg_cost = cost_amount / shares if shares else 0.0
        cursor.execute(
            """INSERT INTO finance.positions
               (customer_id, product_code, shares, cost_amount, avg_cost, opened_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, now(), now())
               ON CONFLICT (customer_id, product_code) DO UPDATE SET
                 shares = EXCLUDED.shares,
                 cost_amount = EXCLUDED.cost_amount,
                 avg_cost = EXCLUDED.avg_cost,
                 updated_at = now()""",
            (cid, product_code, shares, cost_amount, avg_cost),
        )

    def list_positions(self, customer_id: str) -> list[dict[str, Any]]:
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """SELECT * FROM finance.positions
                       WHERE customer_id = %s ORDER BY updated_at DESC, product_code""",
                    (customer_id.upper(),),
                )
                rows = cursor.fetchall()
                result = _dict_rows(cursor, rows)
            finally:
                cursor.close()
        return result

    def list_orders(self, customer_id: str, limit: int = 100) -> list[dict[str, Any]]:
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """SELECT * FROM finance.orders
                       WHERE customer_id = %s ORDER BY created_at DESC, order_id DESC LIMIT %s""",
                    (customer_id.upper(), max(1, min(int(limit), 500))),
                )
                rows = cursor.fetchall()
                result = _dict_rows(cursor, rows)
            finally:
                cursor.close()
        return result

    def list_transactions(self, customer_id: str, limit: int = 100) -> list[dict[str, Any]]:
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """SELECT * FROM finance.cash_transactions
                       WHERE customer_id = %s ORDER BY created_at DESC LIMIT %s""",
                    (customer_id.upper(), max(1, min(int(limit), 500))),
                )
                rows = cursor.fetchall()
                result = _dict_rows(cursor, rows)
            finally:
                cursor.close()
        return result

    def realized_pnl_total(self, customer_id: str) -> float:
        """累计已实现盈亏（卖出成交之和）。"""
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """SELECT COALESCE(SUM(realized_pnl), 0) AS total FROM finance.orders
                       WHERE customer_id = %s AND side = 'sell'""",
                    (customer_id.upper(),),
                )
                row = cursor.fetchone()
                total = row[0] if row else 0
            finally:
                cursor.close()
        return float(total or 0)


class PostgresProductLibrary(_PostgresBaseStore):
    """产品库的 PostgreSQL 存储。"""

    def query_by_codes(self, codes: list[str]) -> list[dict[str, Any]]:
        """按代码批量读取产品，保留输入顺序并忽略未找到的代码。"""
        normalized = list(dict.fromkeys(str(code).strip() for code in codes if str(code).strip()))
        products: list[dict[str, Any]] = []
        for code in normalized:
            product = self.query_by_code(code)
            if product is not None:
                products.append(product)
        return products

    def query_by_code(self, code: str) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "SELECT * FROM finance.products WHERE code = %s",
                    (str(code).strip(),),
                )
                row = cursor.fetchone()
                result = self._build_product(cursor, row) if row else None
            finally:
                cursor.close()
        return result

    def query_by_name(self, name: str) -> dict[str, Any] | None:
        keyword = str(name).strip()
        if not keyword:
            return None
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "SELECT * FROM finance.products WHERE name LIKE %s ORDER BY code LIMIT 1",
                    (f"%{keyword}%",),
                )
                row = cursor.fetchone()
                result = self._build_product(cursor, row) if row else None
            finally:
                cursor.close()
        return result

    def search_by_name(self, name: str) -> list[dict[str, Any]]:
        """返回名称模糊匹配的全部候选，供上层处理歧义。

        刻意**不**加 ``LIMIT 1``：静默取第一条会让用户拿到不相关的产品且无从察觉，
        由调用方（解析器）在多个候选时给出澄清。已下架商品同样被排除 —— 它们不该
        再作为推荐候选出现，但仍然可以被 ``query_by_code`` 读到以支持赎回与对账。
        """
        keyword = str(name).strip()
        if not keyword:
            return []
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """SELECT code, name, type, scale FROM finance.products
                       WHERE name LIKE %s AND is_active ORDER BY code""",
                    (f"%{keyword}%",),
                )
                rows = cursor.fetchall()
                result = _dict_rows(cursor, rows)
            finally:
                cursor.close()
        return result

    def list_products(
        self, product_type: str = "fund", *, include_inactive: bool = False,
    ) -> list[dict[str, Any]]:
        """货架商品摘要。

        默认只返回上架商品（``is_active``），管理后台传 ``include_inactive=True``
        以便把下架商品也列出来重新上架。
        """
        self._ensure_schema()
        clause = "" if include_inactive else "AND is_active "
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    f"SELECT code, name, type, scale, is_active FROM finance.products "
                    f"WHERE type = %s {clause}ORDER BY code",
                    (product_type or "fund",),
                )
                rows = cursor.fetchall()
                result = _dict_rows(cursor, rows)
            finally:
                cursor.close()
        return result

    def set_product_active(self, code: str, active: bool) -> bool:
        """上架/下架商品（软状态），返回是否命中商品。

        不用 ``delete_product``：``finance.orders.product_code`` 外键指向
        ``finance.products(code)`` 且未声明级联，删除有成交记录的商品会外键失败；
        即便删得掉，历史成交与既有持仓也会失去可解释的标的。
        """
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "UPDATE finance.products SET is_active = %s WHERE code = %s",
                    (bool(active), str(code).strip()),
                )
                count = cursor.rowcount
            finally:
                cursor.close()
        return count > 0

    def upsert_product(self, data: dict[str, Any]) -> bool:
        code = str(data.get("code", "")).strip()
        if not code or not str(data.get("name", "")).strip():
            return False
        self._ensure_schema()
        fields = (
            "code", "name", "type", "establish_date", "scale", "manager", "company",
            "management_fee", "custody_fee", "subscription_fee", "redemption_fee",
            "risk_level", "recommended_holding_period", "investment_target", "investment_strategy",
        )
        text_defaults = {"name", "type", "establish_date", "manager", "company",
                         "redemption_fee", "risk_level", "recommended_holding_period",
                         "investment_target", "investment_strategy"}
        values = [data.get(f, "" if f in text_defaults else None) for f in fields]
        values[0] = code
        values[1] = str(values[1]).strip()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    f"INSERT INTO finance.products ({', '.join(fields)}) VALUES ({', '.join('%s' for _ in fields)}) "
                    "ON CONFLICT (code) DO UPDATE SET "
                    + ", ".join(f"{field}=EXCLUDED.{field}" for field in fields[1:]),
                    values,
                )
            finally:
                cursor.close()
        return True

    def upsert_holdings(self, code: str, holdings: list[dict[str, Any]]) -> bool:
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute("SELECT 1 FROM finance.products WHERE code = %s", (code,))
                if cursor.fetchone() is None:
                    return False
                cursor.execute("DELETE FROM finance.product_holdings WHERE product_code = %s", (code,))
                for item in holdings:
                    cursor.execute(
                        """INSERT INTO finance.product_holdings
                           (product_code, stock_name, stock_code, weight, rank, report_date)
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                        (code, item.get("stock_name", item.get("name", "")),
                         item.get("stock_code", item.get("code", "")),
                         item.get("weight"), item.get("rank"), item.get("report_date", "")),
                    )
            finally:
                cursor.close()
        return True

    def upsert_performance(self, code: str, perf: dict[str, Any]) -> bool:
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute("SELECT 1 FROM finance.products WHERE code = %s", (code,))
                if cursor.fetchone() is None:
                    return False
                cursor.execute(
                    """INSERT INTO finance.product_performance
                       (product_code, nav, return_1m, return_3m, return_6m, return_1y,
                        return_3y, max_drawdown, volatility, sharpe_ratio, update_date)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (code, perf.get("nav"), perf.get("return_1m", perf.get("1m")),
                     perf.get("return_3m", perf.get("3m")), perf.get("return_6m", perf.get("6m")),
                     perf.get("return_1y", perf.get("1y")), perf.get("return_3y", perf.get("3y")),
                     perf.get("max_drawdown"), perf.get("volatility"), perf.get("sharpe_ratio"),
                     perf.get("update_date", "")),
                )
            finally:
                cursor.close()
        return True

    def delete_product(self, code: str) -> bool:
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute("DELETE FROM finance.products WHERE code = %s", (code,))
                count = cursor.rowcount
            finally:
                cursor.close()
        return count > 0

    @staticmethod
    def _freshness(as_of: str, max_age_days: int) -> str:
        """按截止日期判断区块新鲜度；无法解析时保守返回 unknown。"""
        if not as_of:
            return "unknown"
        try:
            parsed = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return "unknown"
        return "stale" if datetime.now(timezone.utc) - parsed > timedelta(days=max_age_days) else "fresh"

    def _build_product(self, cursor: Any, row: Any) -> dict[str, Any]:
        from finance_agent.config import (
            PRODUCT_HOLDINGS_FRESHNESS_DAYS,
            PRODUCT_PERFORMANCE_FRESHNESS_DAYS,
        )

        product = _dict_rows(cursor, [row])[0]
        cursor.execute(
            "SELECT stock_name, stock_code, weight, rank, report_date FROM finance.product_holdings WHERE product_code = %s ORDER BY rank, id",
            (product["code"],),
        )
        holdings = cursor.fetchall()
        cursor.execute(
            """SELECT nav, return_1m, return_3m, return_6m, return_1y, return_3y,
                      max_drawdown, volatility, sharpe_ratio, update_date
               FROM finance.product_performance WHERE product_code = %s ORDER BY id DESC LIMIT 1""",
            (product["code"],),
        )
        performance = cursor.fetchone()
        fee_fields = ("management_fee", "custody_fee", "subscription_fee", "redemption_fee")
        fee = {field: product.pop(field, None) for field in fee_fields}
        holdings_list = _dict_rows(cursor, holdings)
        # 逐区块标注来源、截止日期与新鲜度：产品结论只能建立在可溯源的事实上。
        basic_info = {**product, "source": "postgresql", "as_of": "", "freshness": "unknown"}
        holdings_as_of = max((str(item.get("report_date") or "") for item in holdings_list), default="")
        performance_data = _dict_rows(cursor, [performance])[0] if performance else {}
        performance_as_of = str(performance_data.get("update_date") or "")
        return {
            "basic_info": basic_info,
            "holdings": {
                "top10": holdings_list[:10],
                "concentration": sum((h.get("weight") or 0) for h in holdings_list[:10]),
                "source": "postgresql",
                "as_of": holdings_as_of,
                "freshness": self._freshness(holdings_as_of, PRODUCT_HOLDINGS_FRESHNESS_DAYS),
            },
            "performance": {**performance_data, "source": "postgresql", "as_of": performance_as_of,
                            "freshness": self._freshness(performance_as_of, PRODUCT_PERFORMANCE_FRESHNESS_DAYS)},
            "fee": fee,
        }
