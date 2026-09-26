"""市场级数据源（指数/宽度/北向）适配器出口测试，全部离线（夹具驱动）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from finance_agent.infrastructure.market_data.board_codes import (
    INDEX_SYMBOLS,
    canonical_index,
    is_index_symbol,
)
from finance_agent.infrastructure.market_data.normalization import (
    normalize_breadth_record,
    normalize_index_daily_records,
    normalize_margin_summary,
    normalize_northbound_holdings,
    normalize_policy_news_records,
)
from finance_agent.infrastructure.market_data.providers import UnsupportedProviderCapability


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


def test_normalize_margin_summary_takes_latest_combined_row():
    """两市合计口径：按日期升序，取最后一行；单位已是亿元。"""
    payload = [
        {"日期": "2026-09-09", "融资余额": 26193.911321, "融券余额": 292.094317,
         "融资买入额": 1549.673373, "融券卖出额": 10.303606},
        {"日期": "2026-09-10", "融资余额": 26171.760561, "融券余额": 291.914989,
         "融资买入额": 1363.108363, "融券卖出额": 8.620038},
    ]

    record = normalize_margin_summary(payload)

    assert record["as_of"] == "2026-09-10"
    assert record["financing_balance_yi"] == 26171.760561
    assert record["financing_buy_yi"] == 1363.108363
    assert record["total_balance_yi"] == pytest.approx(26463.67555)


def test_normalize_margin_summary_requires_financing_balance():
    assert normalize_margin_summary([]) is None
    assert normalize_margin_summary([{"日期": "2026-09-10"}]) is None


def test_normalize_northbound_holdings_picks_last_nonzero_quarter():
    """持股市值改为季度披露：跳过 0 值行，取最近一个有值的季度点位。"""
    payload = [
        {"日期": "2026-03-31", "持股市值": 2578453000000},
        {"日期": "2026-06-30", "持股市值": 3102375003773},
        {"日期": "2026-09-11", "持股市值": 0.0},
    ]

    record = normalize_northbound_holdings(payload)

    assert record["as_of"] == "2026-06-30"
    assert record["holdings_value_yuan"] == 3102375003773


def test_normalize_northbound_holdings_none_without_valid_value():
    assert normalize_northbound_holdings([{"日期": "2026-09-11", "持股市值": 0}]) is None
    assert normalize_northbound_holdings([]) is None


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

    def stock_margin_account_info(self):
        return _FakeFrame([
            {"日期": "2026-09-09", "融资余额": 26193.911321, "融券余额": 292.094317,
             "融资买入额": 1549.673373, "融券卖出额": 10.303606},
            {"日期": "2026-09-10", "融资余额": 26171.760561, "融券余额": 291.914989,
             "融资买入额": 1363.108363, "融券卖出额": 8.620038},
        ])

    def stock_hsgt_hist_em(self, symbol: str = "北向资金"):
        assert symbol == "北向资金"
        return _FakeFrame([
            {"日期": "2026-03-31", "持股市值": 2578453000000},
            {"日期": "2026-06-30", "持股市值": 3102375003773},
        ])


def _akshare(monkeypatch):
    from finance_agent.infrastructure.market_data.akshare_provider import AkshareDataSource

    provider = object.__new__(AkshareDataSource)
    provider.ak = _FakeAk()
    return provider


def test_akshare_index_daily_normalizes_and_caches(monkeypatch):
    provider = _akshare(monkeypatch)
    monkeypatch.setattr("finance_agent.infrastructure.market_data.akshare_provider.cache_read", lambda *a, **k: None)
    written: list[Any] = []

    def fake_write(namespace, key, records):
        written.append((namespace, key, records))

    monkeypatch.setattr("finance_agent.infrastructure.market_data.akshare_provider.cache_write", fake_write)

    rows = provider.get_index_daily("sh000001", start_date="2026-09-10")

    assert [row["trade_date"] for row in rows] == ["2026-09-10", "2026-09-11"]
    assert rows[-1]["close"] == "3888.1"
    assert written and written[0][0] == "index_daily"


def test_akshare_market_breadth_returns_unified_snapshot(monkeypatch):
    provider = _akshare(monkeypatch)
    monkeypatch.setattr("finance_agent.infrastructure.market_data.akshare_provider.cache_read", lambda *a, **k: None)
    monkeypatch.setattr("finance_agent.infrastructure.market_data.akshare_provider.cache_write", lambda *a, **k: None)

    record = provider.get_market_breadth()

    assert record["advancing"] == 604
    assert record["declining"] == 4567
    assert record["activity"] == pytest.approx(11.57)
    assert record["as_of"] == "2026-09-11"


def test_akshare_margin_summary_returns_combined_snapshot(monkeypatch):
    provider = _akshare(monkeypatch)
    monkeypatch.setattr("finance_agent.infrastructure.market_data.akshare_provider.cache_read", lambda *a, **k: None)
    monkeypatch.setattr("finance_agent.infrastructure.market_data.akshare_provider.cache_write", lambda *a, **k: None)

    record = provider.get_margin_summary()

    assert record["as_of"] == "2026-09-10"
    assert record["financing_balance_yi"] == 26171.760561
    assert record["total_balance_yi"] == pytest.approx(26463.67555)


def test_akshare_northbound_holdings_returns_quarter_point(monkeypatch):
    provider = _akshare(monkeypatch)
    monkeypatch.setattr("finance_agent.infrastructure.market_data.akshare_provider.cache_read", lambda *a, **k: None)
    monkeypatch.setattr("finance_agent.infrastructure.market_data.akshare_provider.cache_write", lambda *a, **k: None)

    record = provider.get_northbound_holdings()

    assert record["as_of"] == "2026-06-30"
    assert record["holdings_value_yuan"] == 3102375003773
    assert "季度" in record["note"]


def test_akshare_rejects_stock_code_as_index(monkeypatch):
    provider = _akshare(monkeypatch)
    with pytest.raises(UnsupportedProviderCapability):
        provider.get_index_daily("600519")


def test_baostock_declares_market_capabilities_unsupported():
    from finance_agent.infrastructure.market_data.baostock_provider import BaostockDataSource

    provider = object.__new__(BaostockDataSource)
    with pytest.raises(UnsupportedProviderCapability):
        provider.get_market_breadth()
    with pytest.raises(UnsupportedProviderCapability):
        provider.get_margin_summary()
    with pytest.raises(UnsupportedProviderCapability):
        provider.get_northbound_holdings()


def test_provider_manager_routes_index_daily_with_fallback(monkeypatch):
    """AKShare 失败时按方法降级到 BaoStock，且 unsupported 与 failures 分开记录。"""
    from finance_agent.infrastructure.market_data.provider_manager import ProviderManager

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


# ── 融资余额日环比 ─────────────────────────────────────────────────────────────

def test_normalize_margin_summary_adds_day_over_day_change():
    payload = [
        {"日期": "2026-09-09", "融资余额": 26193.911321, "融券余额": 292.094317},
        {"日期": "2026-09-10", "融资余额": 26171.760561, "融券余额": 291.914989},
    ]

    record = normalize_margin_summary(payload)

    assert record["financing_balance_prev_yi"] == 26193.911321
    assert record["financing_balance_chg_yi"] == pytest.approx(-22.15076, abs=1e-4)


def test_normalize_margin_summary_single_row_has_no_change():
    record = normalize_margin_summary([
        {"日期": "2026-09-10", "融资余额": 26171.760561, "融券余额": 291.914989},
    ])

    assert "financing_balance_chg_yi" not in record
    assert "financing_balance_prev_yi" not in record


# ── 政策新闻归一化 ─────────────────────────────────────────────────────────────

def test_normalize_policy_news_sina_extracts_title_from_content():
    """新浪全球快讯只有 时间/内容，标题需从内容开头的【…】提取。"""
    payload = [
        {"时间": "2026-09-13 10:43:43", "内容": "【央行开展逆回购操作】为维护流动性合理充裕..."},
    ]

    records = normalize_policy_news_records(payload)

    assert len(records) == 1
    assert records[0]["title"] == "央行开展逆回购操作"
    assert records[0]["datetime"] == "2026-09-13 10:43:43"


def test_normalize_policy_news_ths_uses_title_column_and_sorts_desc():
    payload = [
        {"标题": "较早的新闻", "内容": "x", "发布时间": "2026-09-12 08:00:00", "链接": "u"},
        {"标题": "较新的新闻", "内容": "y", "发布时间": "2026-09-13 09:00:00", "链接": "u"},
    ]

    records = normalize_policy_news_records(payload)

    assert [r["title"] for r in records] == ["较新的新闻", "较早的新闻"]


def test_normalize_policy_news_cctv_date_field():
    payload = [{"date": "20260912", "title": "新闻联播头条", "content": "全文"}]

    records = normalize_policy_news_records(payload)

    assert records[0]["datetime"] == "2026-09-12"
    assert records[0]["title"] == "新闻联播头条"


def test_normalize_policy_news_drops_untitled_records():
    assert normalize_policy_news_records([{"时间": "2026-09-13", "内容": "无标题无括号"}]) == []


# ── 政策事件确定性筛选 ─────────────────────────────────────────────────────────

def test_policy_event_filter_categorizes_by_priority(monkeypatch):
    """命中多类时取优先级靠前类目（货币政策优先于产业政策）。"""
    from datetime import datetime

    from finance_agent.domains.market.expert import collectors as marketdata

    recent = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    raw = [
        {"datetime": recent, "title": "央行降准并发布产业规划", "content": ""},
        {"datetime": recent, "title": "证监会发布减持新规", "content": ""},
        {"datetime": recent, "title": "某公司发布新品", "content": ""},
    ]

    class _M:
        def get_policy_news(self):
            return raw

    monkeypatch.setattr(marketdata, "get_provider_manager", lambda: _M())
    data = marketdata.get_policy_events_data()

    categories = {e["title"]: e["category"] for e in data["events"]}
    assert categories["央行降准并发布产业规划"] == "货币政策"
    assert categories["证监会发布减持新规"] == "资本市场监管"
    assert "某公司发布新品" not in categories          # 非政策事件被筛掉
    assert data["categories_summary"] == {"货币政策": 1, "资本市场监管": 1}


def test_policy_event_filter_drops_stale_records(monkeypatch):
    """超出近 N 天窗口的政策事件被确定性过滤掉。"""
    from datetime import datetime, timedelta

    from finance_agent.domains.market.expert import collectors as marketdata

    stale = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    fresh = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    class _M:
        def get_policy_news(self):
            return [
                {"datetime": stale, "title": "央行降准", "content": ""},
                {"datetime": fresh, "title": "证监会发布减持新规", "content": ""},
            ]

    monkeypatch.setattr(marketdata, "get_provider_manager", lambda: _M())
    data = marketdata.get_policy_events_data()

    titles = [e["title"] for e in data["events"]]
    assert "证监会发布减持新规" in titles
    assert "央行降准" not in titles


def test_policy_event_source_failure_reports_limitation(monkeypatch):
    from finance_agent.domains.market.expert import collectors as marketdata

    class _M:
        def get_policy_news(self):
            raise RuntimeError("network down")

    monkeypatch.setattr(marketdata, "get_provider_manager", lambda: _M())
    data = marketdata.get_policy_events_data()

    assert data["events"] == []
    assert "policy_news" in data["limitations"]
