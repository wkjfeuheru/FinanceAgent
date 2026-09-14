"""PostgreSQL 业务存储层。

将原本 SQLite 承载的表（画像/会话/消息/认证/产品库）迁移到 PostgreSQL，
接口与既有 SQLite 实现保持一致，供 ``get_database`` / ``get_user_store`` /
``get_product_library`` 在配置 ``POSTGRES_DSN`` 时切换使用。
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

TOKEN_TTL_SECONDS = 7 * 24 * 3600


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
        from finance_agent.data.postgres_schema import (
            AGENT_RUNTIME_SCHEMA_SQL,
            BASE_SCHEMA_SQL,
            HYBRID_ORCHESTRATION_SCHEMA_SQL,
        )

        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(BASE_SCHEMA_SQL)
                cursor.execute(AGENT_RUNTIME_SCHEMA_SQL)
                cursor.execute(HYBRID_ORCHESTRATION_SCHEMA_SQL)
            finally:
                cursor.close()
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
    from finance_agent.orchestrator.run_state import RunStateStore

    return RunStateStore(
        checkpointer=checkpointer,
        business_store=business_store,
    ).load(customer_id, conversation_id)


class PostgresAuthStore(_PostgresBaseStore):
    """认证（用户 + 会话）的 PostgreSQL 存储。"""

    def register(self, username: str, password: str, display_name: str = "") -> dict[str, Any]:
        username = (username or "").strip()
        if len(username) < 2:
            raise ValueError("用户名至少需要 2 个字符")
        if len(password) < 6:
            raise ValueError("密码至少需要 6 个字符")
        salt = secrets.token_hex(16)
        name = display_name.strip() or username
        self._ensure_schema()
        try:
            with self._transaction() as connection:
                cursor = connection.cursor()
                try:
                    cursor.execute(
                        """INSERT INTO finance.users
                           (customer_id, username, display_name, password_hash, salt, created_at)
                           VALUES (NULL, %s, %s, %s, %s, %s) RETURNING id""",
                        (username, name, _hash_password(password, salt), salt,
                         datetime.now().isoformat(timespec="seconds")),
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
        return {"customer_id": customer_id, "username": username, "display_name": name}

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
                "display_name": user["display_name"], "token": token}

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

    def delete_user(self, customer_id: str) -> bool:
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "DELETE FROM finance.users WHERE customer_id = %s",
                    (customer_id.upper(),),
                )
                count = cursor.rowcount
            finally:
                cursor.close()
        return count > 0

    def _public(self, cursor: Any, row: Any) -> dict[str, Any]:
        data = _dict_rows(cursor, [row])[0]
        return {key: data[key] for key in ("username", "customer_id", "display_name", "created_at")}


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
        """返回名称模糊匹配的全部产品候选，供上层处理歧义。

        刻意**不**加 ``LIMIT 1``：静默取第一条会让用户拿到不相关的产品且无从察觉，
        由调用方（解析器）在多个候选时给出澄清。
        """
        keyword = str(name).strip()
        if not keyword:
            return []
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "SELECT code, name, type, scale FROM finance.products WHERE name LIKE %s ORDER BY code",
                    (f"%{keyword}%",),
                )
                rows = cursor.fetchall()
                result = _dict_rows(cursor, rows)
            finally:
                cursor.close()
        return result

    def list_products(self, product_type: str = "fund") -> list[dict[str, Any]]:
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "SELECT code, name, type, scale FROM finance.products WHERE type = %s ORDER BY code",
                    (product_type or "fund",),
                )
                rows = cursor.fetchall()
                result = _dict_rows(cursor, rows)
            finally:
                cursor.close()
        return result

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
