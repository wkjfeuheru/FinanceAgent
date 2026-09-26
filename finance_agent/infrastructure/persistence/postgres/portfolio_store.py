"""模拟交易账户、流水、委托与持仓的 PostgreSQL 适配器。"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Iterator

from finance_agent.infrastructure.persistence.postgres.connection import _PostgresBaseStore, _dict_rows

class PostgresPortfolioStore(_PostgresBaseStore):
    """模拟交易账户、流水、委托与持仓的 PostgreSQL 存储。

    只做数据读写与行锁，不含费率与盈亏口径 —— 那些属于
    ``finance_agent.domains.portfolio.service``，保证 REST 与 Agent 走同一套计算。
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

