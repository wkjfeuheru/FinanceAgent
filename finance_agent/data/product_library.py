"""金融产品库 SQLite 访问层。"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from finance_agent.config import PRODUCT_LIBRARY_DB_PATH


class ProductLibrary:
    """产品基础信息、持仓和业绩数据的 SQLite 存储层。"""

    def __init__(self, db_path: str = PRODUCT_LIBRARY_DB_PATH):
        """初始化数据库路径并创建产品库表。"""
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """创建一次性 SQLite 连接并在成功后提交事务。"""
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        """创建产品库所需的关系型数据表和索引。"""
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS products (
                    code TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL DEFAULT 'fund',
                    establish_date TEXT NOT NULL DEFAULT '',
                    scale REAL,
                    manager TEXT NOT NULL DEFAULT '',
                    company TEXT NOT NULL DEFAULT '',
                    management_fee REAL,
                    custody_fee REAL,
                    subscription_fee REAL,
                    redemption_fee TEXT NOT NULL DEFAULT '',
                    risk_level TEXT NOT NULL DEFAULT '',
                    investment_target TEXT NOT NULL DEFAULT '',
                    investment_strategy TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS product_holdings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_code TEXT NOT NULL,
                    stock_name TEXT NOT NULL,
                    stock_code TEXT NOT NULL DEFAULT '',
                    weight REAL,
                    rank INTEGER,
                    report_date TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY (product_code) REFERENCES products(code) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS product_performance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_code TEXT NOT NULL,
                    nav REAL,
                    return_1m REAL,
                    return_3m REAL,
                    return_6m REAL,
                    return_1y REAL,
                    return_3y REAL,
                    max_drawdown REAL,
                    volatility REAL,
                    sharpe_ratio REAL,
                    update_date TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY (product_code) REFERENCES products(code) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_products_name ON products(name);
                CREATE INDEX IF NOT EXISTS idx_holdings_product ON product_holdings(product_code, rank);
                CREATE INDEX IF NOT EXISTS idx_performance_product ON product_performance(product_code, id DESC);
                """
            )

    def query_by_code(self, code: str) -> dict[str, Any] | None:
        """按产品代码查询基础信息、持仓、业绩和费率。"""
        with self.connect() as db:
            row = db.execute("SELECT * FROM products WHERE code = ?", (str(code).strip(),)).fetchone()
            if row is None:
                return None
            return self._build_product(db, row)

    def query_by_name(self, name: str) -> dict[str, Any] | None:
        """按产品名称模糊查询并返回第一条匹配产品。"""
        keyword = str(name).strip()
        if not keyword:
            return None
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM products WHERE name LIKE ? ORDER BY code LIMIT 1",
                (f"%{keyword}%",),
            ).fetchone()
            return self._build_product(db, row) if row else None

    def list_products(self, product_type: str = "fund") -> list[dict[str, Any]]:
        """列出指定类型产品的基础信息和规模。"""
        with self.connect() as db:
            rows = db.execute(
                "SELECT code, name, type, scale FROM products WHERE type = ? ORDER BY code",
                (product_type or "fund",),
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_product(self, data: dict[str, Any]) -> bool:
        """写入或更新产品基础信息及费率字段。"""
        code = str(data.get("code", "")).strip()
        if not code or not str(data.get("name", "")).strip():
            return False
        fields = (
            "code", "name", "type", "establish_date", "scale", "manager", "company",
            "management_fee", "custody_fee", "subscription_fee", "redemption_fee",
            "risk_level", "investment_target", "investment_strategy",
        )
        values = [data.get(field, "" if field in {"name", "type", "establish_date", "manager", "company", "redemption_fee", "risk_level", "investment_target", "investment_strategy"} else None) for field in fields]
        values[0] = code
        values[1] = str(values[1]).strip()
        with self.connect() as db:
            db.execute(
                f"INSERT INTO products ({', '.join(fields)}) VALUES ({', '.join('?' for _ in fields)}) "
                "ON CONFLICT(code) DO UPDATE SET "
                + ", ".join(f"{field}=excluded.{field}" for field in fields[1:]),
                values,
            )
        return True

    def upsert_holdings(self, code: str, holdings: list[dict[str, Any]]) -> bool:
        """替换指定产品的持仓明细。"""
        with self.connect() as db:
            if db.execute("SELECT 1 FROM products WHERE code = ?", (code,)).fetchone() is None:
                return False
            db.execute("DELETE FROM product_holdings WHERE product_code = ?", (code,))
            db.executemany(
                "INSERT INTO product_holdings (product_code, stock_name, stock_code, weight, rank, report_date) VALUES (?, ?, ?, ?, ?, ?)",
                [(code, item.get("stock_name", item.get("name", "")), item.get("stock_code", item.get("code", "")), item.get("weight"), item.get("rank"), item.get("report_date", "")) for item in holdings],
            )
        return True

    def upsert_performance(self, code: str, perf: dict[str, Any]) -> bool:
        """写入指定产品的一条业绩快照。"""
        with self.connect() as db:
            if db.execute("SELECT 1 FROM products WHERE code = ?", (code,)).fetchone() is None:
                return False
            db.execute(
                "INSERT INTO product_performance (product_code, nav, return_1m, return_3m, return_6m, return_1y, return_3y, max_drawdown, volatility, sharpe_ratio, update_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (code, perf.get("nav"), perf.get("return_1m", perf.get("1m")), perf.get("return_3m", perf.get("3m")), perf.get("return_6m", perf.get("6m")), perf.get("return_1y", perf.get("1y")), perf.get("return_3y", perf.get("3y")), perf.get("max_drawdown"), perf.get("volatility"), perf.get("sharpe_ratio"), perf.get("update_date", "")),
            )
        return True

    def delete_product(self, code: str) -> bool:
        """删除产品及其关联的持仓和业绩数据。"""
        with self.connect() as db:
            cursor = db.execute("DELETE FROM products WHERE code = ?", (code,))
            return cursor.rowcount > 0

    def _build_product(self, db: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        """将产品基础行和关联数据组装为统一结构。"""
        product = dict(row)
        holdings = db.execute(
            "SELECT stock_name, stock_code, weight, rank, report_date FROM product_holdings WHERE product_code = ? ORDER BY rank, id",
            (product["code"],),
        ).fetchall()
        performance = db.execute(
            "SELECT nav, return_1m, return_3m, return_6m, return_1y, return_3y, max_drawdown, volatility, sharpe_ratio, update_date FROM product_performance WHERE product_code = ? ORDER BY id DESC LIMIT 1",
            (product["code"],),
        ).fetchone()
        fee_fields = ("management_fee", "custody_fee", "subscription_fee", "redemption_fee")
        fee = {field: product.pop(field) for field in fee_fields}
        basic_info = product
        return {
            "basic_info": basic_info,
            "holdings": {"top10": [dict(item) for item in holdings[:10]], "concentration": sum((item["weight"] or 0) for item in holdings[:10])},
            "performance": dict(performance) if performance else {},
            "fee": fee,
        }
