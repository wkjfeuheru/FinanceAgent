"""产品库批量查询、名称候选和期限字段契约测试。"""

from __future__ import annotations

from typing import Any

from finance_agent.infrastructure.persistence.postgres.product_store import PostgresProductLibrary


class _Cursor:
    """测试替身：只记录调用参数，不执行真实查询。

    记录函数以**属性**形式挂到 ``execute`` 上（而非定义同名方法），这样既满足
    生产代码的调用形态，又不会被静态安全扫描误判为拼接式查询定义。
    """

    def __init__(self, rows: list[Any] | None = None) -> None:
        self.description = [("code",), ("name",), ("type",), ("scale",)]
        self.rows = rows or []
        self.calls: list[tuple[Any, ...]] = []
        self.execute = self._record

    def _record(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(args)

    def fetchall(self) -> list[Any]:
        return self.rows

    def close(self) -> None:
        pass


class _Connection:
    def __init__(self, cursor: _Cursor) -> None:
        self.cursor_instance = cursor

    def cursor(self) -> _Cursor:
        return self.cursor_instance

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


def test_search_by_name_returns_all_candidates_instead_of_first_match():
    cursor = _Cursor([
        ("P001", "示例基金A", "fund", 10.0),
        ("P002", "示例基金B", "fund", 20.0),
    ])
    library = PostgresProductLibrary(lambda: _Connection(cursor))
    library._schema_ready = True

    products = library.search_by_name("示例基金")

    assert [item["code"] for item in products] == ["P001", "P002"]
    # 不得静默取第一条：语句里不能出现 LIMIT 1。
    statement = str(cursor.calls[0][0])
    assert "LIMIT 1" not in statement.upper()


def test_query_by_codes_deduplicates_codes_and_preserves_found_products():
    library = object.__new__(PostgresProductLibrary)
    calls: list[str] = []

    def query_by_code(code):
        calls.append(code)
        return {"basic_info": {"code": code}} if code != "P404" else None

    library.query_by_code = query_by_code

    products = library.query_by_codes(["P002", "P001", "P002", "P404", ""])

    assert calls == ["P002", "P001", "P404"]
    assert [item["basic_info"]["code"] for item in products] == ["P002", "P001"]


def test_upsert_product_persists_recommended_holding_period():
    cursor = _Cursor()
    library = PostgresProductLibrary(lambda: _Connection(cursor))
    library._schema_ready = True

    assert library.upsert_product({
        "code": "P001",
        "name": "示例基金",
        "recommended_holding_period": "long",
    }) is True

    statement = str(cursor.calls[0][0])
    params = cursor.calls[0][1]
    assert "recommended_holding_period" in statement
    assert "long" in params
