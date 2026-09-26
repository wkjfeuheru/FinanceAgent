"""产品库 PostgreSQL 适配器。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from finance_agent.infrastructure.persistence.postgres.connection import _PostgresBaseStore, _dict_rows

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

    def list_active_names(self) -> list[dict[str, Any]]:
        """返回全部在架产品的 (code, name)，供名称近似/简称匹配兜底。

        仅取代码与名称两列：近似匹配只需这两者，避免拉全量明细。
        """
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "SELECT code, name FROM finance.products WHERE is_active ORDER BY code"
                )
                rows = cursor.fetchall()
                return [
                    {"code": str(row[0]).strip(), "name": str(row[1]).strip()}
                    for row in rows
                    if row and row[0] and row[1]
                ]
            finally:
                cursor.close()

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
        from finance_agent.infrastructure.settings import (
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

