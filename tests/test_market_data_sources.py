"""市场级数据源（指数/宽度/北向）适配器出口测试，全部离线（夹具驱动）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from finance_agent.data.board_codes import (
    INDEX_SYMBOLS,
    canonical_index,
    is_index_symbol,
)
from finance_agent.data.normalization import (
    normalize_breadth_record,
    normalize_index_daily_records,
    normalize_northbound_records,
)
from finance_agent.data.providers import UnsupportedProviderCapability


# ── 指数符号命名空间 ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("sh000001", True),
    ("sh.000001", True),
    ("SH000300", True),
    ("sz399006", True),
    ("000001", False),   # 纯数字是股票代码（平安银行），绝不猜成指数
    ("600519", False),
])
def test_is_index_symbol_requires_market_prefix(text, expected):
    assert is_index_symbol(text) is expected


def test_canonical_index_accepts_prefixed_suffix_and_names():
    assert canonical_index("sh.000001") == "sh000001"
    assert canonical_index("000001.SH") == "sh000001"
    assert canonical_index("上证指数") == "sh000001"
    assert canonical_index("沪深300") == "sh000300"
    assert canonical_index("创业板指") == "sz399006"


def test_canonical_index_rejects_stock_codes():
    with pytest.raises(UnsupportedProviderCapability):
        canonical_index("600519")


def test_builtin_indices_are_canonical():
    for symbol in INDEX_SYMBOLS:
        assert canonical_index(symbol) == symbol


# ── 归一化 ─────────────────────────────────────────────────────────────────────

def test_normalize_index_daily_maps_sina_columns_and_sorts():
    rows = [
        {"date": "2026-09-11", "open": "3910.9", "high": "3912.3", "low": "3852.0",
         "close": "3888.1", "volume": "57912314500"},
        {"date": "2026-09-10", "open": "3939.0", "high": "3949.2", "low": "3927.3",
         "close": "3934.4", "volume": "48467511400"},
    ]

    normalized = normalize_index_daily_records(rows)

    assert [row["trade_date"] for row in normalized] == ["2026-09-10", "2026-09-11"]
    assert normalized[-1]["close"] == "3888.1"
    assert normalized[-1]["vol"] == "57912314500"


def test_normalize_breadth_record_from_legu_two_column_table():
    payload = [
        {"项目": "上涨", "数值": 604.0},
        {"项目": "涨停", "数值": 40.0},
        {"项目": "下跌", "数值": 4567.0},
        {"项目": "跌停", "数值": 21.0},
        {"项目": "平盘", "数值": 36.0},
        {"项目": "停牌", "数值": 12.0},
        {"项目": "活跃度", "数值": "11.57%"},
        {"项目": "统计日期", "数值": "2026-09-11 15:00:00"},
    ]

    record = normalize_breadth_record(payload)

    assert record is not None
    assert record["as_of"] == "2026-09-11"
    assert record["advancing"] == 604
    assert record["declining"] == 4567
    assert record["limit_up"] == 40
    assert record["limit_down"] == 21
    assert record["activity"] == pytest.approx(11.57)


def test_normalize_breadth_record_returns_none_without_advancing_declining():
    assert normalize_breadth_record([{"项目": "停牌", "数值": 3}]) is None
    assert normalize_breadth_record("not-a-list") is None


def test_normalize_northbound_marks_undisclosed_zero_flow():
    """北向实时净买额自 2024-08 起不再披露（数据源恒返回 0），必须标记未披露。"""
    payload = [
        {"交易日": "2026-09-11", "类型": "沪港通", "板块": "沪股通", "资金方向": "北向",
         "成交净买额": 0.0, "资金净流入": 0.0, "上涨数": 203, "下跌数": 1425},
        {"交易日": "2026-09-11", "类型": "深港通", "板块": "深股通", "资金方向": "北向",
         "成交净买额": 12.5, "资金净流入": 88.0, "上涨数": 231, "下跌数": 1633},
    ]

    channels = normalize_northbound_records(payload)

    assert channels[0]["disclosed"] is False
    assert channels[1]["disclosed"] is True


def test_normalize_northbound_keeps_northbound_channels_only():
    payload = [
        {"交易日": "2026-09-11", "类型": "沪港通", "板块": "沪股通", "资金方向": "北向",
         "成交净买额": 5.2, "资金净流入": 10.0, "上涨数": 203, "下跌数": 1425},
        {"交易日": "2026-09-11", "类型": "沪港通", "板块": "港股通(沪)", "资金方向": "南向",
         "成交净买额": 31.9, "资金净流入": 420.0, "上涨数": 164, "下跌数": 480},
        {"交易日": "2026-09-11", "类型": "深港通", "板块": "深股通", "资金方向": "北向",
         "成交净买额": 12.5, "资金净流入": 88.0, "上涨数": 231, "下跌数": 1633},
    ]

    channels = normalize_northbound_records(payload)

    assert [channel["board"] for channel in channels] == ["沪股通", "深股通"]
    assert all(channel["direction"] == "northbound" for channel in channels)
    assert channels[0]["net_buy_yi"] == 5.2
    assert channels[1]["fund_inflow_yi"] == 88.0
    assert channels[0]["as_of"] == "2026-09-11"


# ── 适配器出口（夹具驱动，不联网） ──────────────────────────────────────────────

class _FakeFrame:
    """模拟 ``DataFrame.to_dict(orient="records")`` 的最小对象。"""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def to_dict(self, orient: str = "records"):
        assert orient == "records"
        return self._rows


class _FakeAk:
    """把三个市场接口替换为夹具返回。"""

    def stock_zh_index_daily(self, symbol: str, **kwargs):
        assert symbol == "sh000001"
        return _FakeFrame([
            {"date": "2026-09-10", "open": "3939.0", "high": "3949.2", "low": "3927.3",
             "close": "3934.4", "volume": "48467511400"},
            {"date": "2026-09-11", "open": "3910.9", "high": "3912.3", "low": "3852.0",
             "close": "3888.1", "volume": "57912314500"},
        ])

    def stock_market_activity_legu(self):
        return _FakeFrame([
            {"项目": "上涨", "数值": 604.0}, {"项目": "下跌", "数值": 4567.0},
            {"项目": "活跃度", "数值": "11.57%"},
            {"项目": "统计日期", "数值": "2026-09-11 15:00:00"},
        ])

    def stock_hsgt_fund_flow_summary_em(self):
        return _FakeFrame([
            {"交易日": "2026-09-11", "类型": "沪港通", "板块": "沪股通", "资金方向": "北向",
             "成交净买额": 5.2, "资金净流入": 88.0, "上涨数": 203, "下跌数": 1425},
        ])


def _akshare(monkeypatch):
    from finance_agent.data.akshare_provider import AkshareDataSource

    provider = object.__new__(AkshareDataSource)
    provider.ak = _FakeAk()
    return provider


def test_akshare_index_daily_normalizes_and_caches(monkeypatch):
    provider = _akshare(monkeypatch)
    monkeypatch.setattr("finance_agent.data.akshare_provider.cache_read", lambda *a, **k: None)
    written: list[Any] = []

    def fake_write(namespace, key, records):
        written.append((namespace, key, records))

    monkeypatch.setattr("finance_agent.data.akshare_provider.cache_write", fake_write)

    rows = provider.get_index_daily("sh000001", start_date="2026-09-10")

    assert [row["trade_date"] for row in rows] == ["2026-09-10", "2026-09-11"]
    assert rows[-1]["close"] == "3888.1"
    assert written and written[0][0] == "index_daily"


def test_akshare_market_breadth_returns_unified_snapshot(monkeypatch):
    provider = _akshare(monkeypatch)
    monkeypatch.setattr("finance_agent.data.akshare_provider.cache_read", lambda *a, **k: None)
    monkeypatch.setattr("finance_agent.data.akshare_provider.cache_write", lambda *a, **k: None)

    record = provider.get_market_breadth()

    assert record["advancing"] == 604
    assert record["declining"] == 4567
    assert record["activity"] == pytest.approx(11.57)
    assert record["as_of"] == "2026-09-11"


def test_akshare_northbound_flow_keeps_note_and_channels(monkeypatch):
    provider = _akshare(monkeypatch)
    monkeypatch.setattr("finance_agent.data.akshare_provider.cache_read", lambda *a, **k: None)
    monkeypatch.setattr("finance_agent.data.akshare_provider.cache_write", lambda *a, **k: None)

    record = provider.get_northbound_flow()

    assert record["as_of"] == "2026-09-11"
    assert record["channels"][0]["board"] == "沪股通"
    assert record["channels"][0]["net_buy_yi"] == pytest.approx(5.2)
    assert "停更" in record["note"]


def test_akshare_rejects_stock_code_as_index(monkeypatch):
    provider = _akshare(monkeypatch)
    with pytest.raises(UnsupportedProviderCapability):
        provider.get_index_daily("600519")


def test_baostock_declares_breadth_and_northbound_unsupported():
    from finance_agent.data.baostock_provider import BaostockDataSource

    provider = object.__new__(BaostockDataSource)
    with pytest.raises(UnsupportedProviderCapability):
        provider.get_market_breadth()
    with pytest.raises(UnsupportedProviderCapability):
        provider.get_northbound_flow()


def test_provider_manager_routes_index_daily_with_fallback(monkeypatch):
    """AKShare 失败时按方法降级到 BaoStock，且 unsupported 与 failures 分开记录。"""
    from finance_agent.data.provider_manager import ProviderManager

    class BrokenAk:
        provider_name = "akshare"

        def is_available(self):
            return True

        def get_index_daily(self, *args, **kwargs):
            raise RuntimeError("akshare down")

    class WorkingBs:
        provider_name = "baostock"

        def is_available(self):
            return True

        def get_index_daily(self, index_symbol, start_date="", end_date=""):
            return [{"trade_date": "2026-09-11", "close": "3888.1"}]

    manager = ProviderManager(
        providers={"akshare": BrokenAk(), "baostock": WorkingBs()},
        order=["akshare", "baostock"],
    )

    rows = manager.get_index_daily("sh000001")

    assert rows[0]["close"] == "3888.1"
    assert manager.last_metadata["source"] == "baostock"
    assert manager.last_metadata["degraded"] is True
    assert manager.last_metadata["failures"][0]["provider"] == "akshare"
