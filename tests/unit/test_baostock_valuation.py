"""BaoStock 日估值取数的回归测试（免 token 的第二路估值来源）。

关键回归点：``get_daily_basic`` 曾无条件抛 "BaoStock 不支持统一日估值接口"，
但实测 ``query_history_k_data_plus`` 支持 ``peTTM/pbMRQ/psTTM/pcfNcfTTM``，
且在 adjustflag=3/2/1 三种口径下数值完全相同——原判断是错的。
"""

from __future__ import annotations

import pytest

from finance_agent.infrastructure.market_data.baostock_provider import BaostockDataSource
from finance_agent.infrastructure.market_data.providers import ProviderUnavailableError, UnsupportedProviderCapability


class StubResult:
    """最小 ResultSet 桩：error_code/fields/next/get_row_data。"""

    def __init__(self, rows, fields) -> None:
        self.error_code = "0"
        self.error_msg = "success"
        self.fields = fields
        self._rows = list(rows)
        self._index = -1

    def next(self) -> bool:
        self._index += 1
        return self._index < len(self._rows)

    def get_row_data(self):
        return self._rows[self._index]


class StubBaostock:
    """可返回含空串估值行的 BaoStock 桩。"""

    FIELDS = ["date", "peTTM", "pbMRQ", "psTTM", "pcfNcfTTM"]

    def __init__(self, *, rows=None) -> None:
        self.calls: list[dict] = []
        self._rows = rows if rows is not None else [
            ["2026-09-10", "19.0", "2.100000", "3.000000", ""],
            ["2026-09-11", "18.0", "2.000000", "2.950000", ""],
        ]

    def login(self):
        return StubResult([], [])

    def logout(self):
        return StubResult([], [])

    def query_history_k_data_plus(self, code, fields, start_date, end_date, frequency, adjustflag):
        self.calls.append({
            "code": code,
            "fields": fields,
            "frequency": frequency,
            "adjustflag": adjustflag,
        })
        return StubResult(self._rows, self.FIELDS)


@pytest.fixture
def provider() -> BaostockDataSource:
    source = BaostockDataSource()
    source.bs = StubBaostock()
    return source


def test_daily_valuation_is_returned_with_canonical_keys(provider):
    rows = provider.get_daily_basic("600519")

    assert [row["trade_date"] for row in rows] == ["2026-09-10", "2026-09-11"]
    latest = rows[-1]
    assert latest["pe_ttm"] == 18.0
    assert latest["pb"] == 2.0
    assert latest["ps_ttm"] == 2.95


def test_request_pins_daily_frequency_and_unadjusted_flag(provider):
    provider.get_daily_basic("600519")

    call = provider.bs.calls[0]
    assert call["code"] == "sh.600519"
    assert call["frequency"] == "d", "周线/月线带估值字段会被服务端以 10004012 拒绝"
    assert call["adjustflag"] == "3"
    assert "peTTM" in call["fields"] and "pbMRQ" in call["fields"]


def test_rows_without_valuation_values_are_dropped(provider):
    """停牌日的空串行必须剔除，否则"最新一根"全是空值、估值看起来仍然缺失。"""
    provider.bs = StubBaostock(rows=[
        ["2026-09-10", "19.0", "2.100000", "3.000000", ""],
        ["2026-09-11", "18.0", "2.000000", "2.950000", ""],
        ["2026-09-12", "", "", "", ""],
    ])

    rows = provider.get_daily_basic("600519")

    assert [row["trade_date"] for row in rows] == ["2026-09-10", "2026-09-11"]


def test_all_empty_rows_report_unavailable(provider):
    provider.bs = StubBaostock(rows=[["2026-09-12", "", "", "", ""]])

    with pytest.raises(ProviderUnavailableError):
        provider.get_daily_basic("600519")


def test_repeated_request_is_served_from_cache(provider):
    first = provider.get_daily_basic("600519")
    second = provider.get_daily_basic("600519")

    assert len(provider.bs.calls) == 1, "命中缓存时不得再次取数"
    assert second == first


def test_beijing_exchange_is_rejected_for_valuation_too(provider):
    """BaoStock 对北交所零支持，估值路径同样必须显式拒绝。"""
    with pytest.raises(UnsupportedProviderCapability):
        provider.get_daily_basic("920799")

    assert provider.bs.calls == []
