"""数据源字段归一化与生产取数到研究评分的端到端回归测试。"""

from __future__ import annotations

import pytest

from finance_agent.infrastructure.market_data.akshare_provider import AkshareDataSource
from finance_agent.infrastructure.market_data.normalization import (
    normalize_basic_records,
    normalize_daily_records,
    normalize_financial_records,
    normalize_valuation_records,
)
from finance_agent.infrastructure.market_data.provider_manager import ProviderManager
from finance_agent.domains.research.contracts import AnalysisKind, AnalysisRequest
from finance_agent.domains.research.rule_engine import RuleEngine
from finance_agent.domains.research.snapshot_builder import SnapshotBuilder


# ── 归一化单元测试 ──────────────────────────────────────────────


def test_akshare_chinese_daily_columns_become_unified_fields():
    rows = normalize_daily_records([
        {"日期": "2026-01-05", "开盘": 10.0, "收盘": 10.5, "最高": 10.6, "最低": 9.9,
         "成交量": 1200, "成交额": 12000.0, "涨跌幅": 5.0, "涨跌额": 0.5, "换手率": 1.2},
    ])

    assert rows[0]["trade_date"] == "2026-01-05"
    assert rows[0]["close"] == 10.5
    assert rows[0]["vol"] == 1200
    assert rows[0]["pct_chg"] == 5.0
    assert rows[0]["change"] == 0.5
    assert "日期" not in rows[0] and "收盘" not in rows[0]


def test_daily_records_are_sorted_ascending_across_vendor_date_formats():
    """厂商返回 YYYYMMDD 且可能倒序，必须统一为升序 ISO 日期。"""
    rows = normalize_daily_records([
        {"trade_date": "20260107", "close": 12.0},
        {"trade_date": "20260105", "close": 10.0},
        {"trade_date": "20260106", "close": 11.0},
    ])

    assert [row["trade_date"] for row in rows] == ["2026-01-05", "2026-01-06", "2026-01-07"]
    assert rows[-1]["close"] == 12.0


def test_dataframe_style_wrapper_is_normalized_in_place():
    payload = normalize_valuation_records({"data": [{"日期": "2026-01-05", "市盈率": 18.0, "市净率": 2.0}]})

    assert payload["data"][0]["pe"] == 18.0
    assert payload["data"][0]["pb"] == 2.0


def test_ttm_and_static_pe_are_never_conflated():
    """PE 口径必须严格区分：``pe`` 不得再以 ``pe_ttm`` 兜底。

    东方财富 stock_value_em 同时返回 ``PE(TTM)`` 与 ``PE(静)``，而
    ``VALUATION_ALIASES["pe"]`` 曾把 ``pe_ttm`` 列为别名，导致取到哪个口径不确定。
    """
    ttm_only = normalize_valuation_records([{"trade_date": "2026-01-05", "pe_ttm": 18.0}])

    assert ttm_only[0]["pe_ttm"] == 18.0
    assert "pe" not in ttm_only[0]

    both = normalize_valuation_records([
        {"trade_date": "2026-01-05", "pe": 20.0, "pe_ttm": 18.0},
    ])

    assert both[0]["pe"] == 20.0
    assert both[0]["pe_ttm"] == 18.0


def test_stock_value_em_and_baostock_valuation_columns_are_unified():
    """东财与 BaoStock 的估值列必须命中统一键，否则估值在归一层会再丢一次。"""
    em = normalize_valuation_records([{
        "数据日期": "2026-01-05", "市净率": 2.0, "总市值": 1.0e12, "流通市值": 8.0e11,
    }])

    assert em[0]["trade_date"] == "2026-01-05"
    assert em[0]["pb"] == 2.0
    assert em[0]["total_mv"] == 1.0e12
    assert em[0]["circ_mv"] == 8.0e11

    baostock = normalize_valuation_records([{
        "date": "2026-01-05", "peTTM": 18.0, "pbMRQ": 2.0, "psTTM": 3.0,
    }])

    assert baostock[0]["trade_date"] == "2026-01-05"
    assert baostock[0]["pe_ttm"] == 18.0
    assert baostock[0]["pb"] == 2.0
    assert baostock[0]["ps_ttm"] == 3.0


def test_static_pe_is_carried_but_never_scored():
    """``pe_lyr`` 是独立规范键：可携带静态 PE，但不得被当作 TTM 参与评分。"""
    from finance_agent.domains.research.scoring import build_scores

    rows = normalize_valuation_records([{"trade_date": "2026-01-05", "pe_lyr": 20.0}])
    assert rows[0]["pe_lyr"] == 20.0

    static_only, _ = build_scores({"pe_lyr": 20.0}, {"adjustment": "forward", "data": []})
    assert static_only["fundamental_score"] is None

    with_pb, _ = build_scores(
        {"pe_lyr": 20.0, "pb": 2.0}, {"adjustment": "forward", "data": []},
    )
    # 只有 PB 可评分时为 _pb_score(2.0)；静态 PE 不得被当成 TTM 拉低均分。
    assert with_pb["fundamental_score"] == 75.0


def test_sina_financial_labels_map_to_research_fields():
    rows = normalize_financial_records([
        {"日期": "2025-12-31", "净资产收益率(%)": 18.2, "加权净资产收益率(%)": 17.1,
         "主营业务收入增长率(%)": 20.5, "净利润增长率(%)": 22.0, "主营业务利润增长率(%)": 9.0},
    ])

    assert rows[0]["end_date"] == "2025-12-31"
    assert rows[0]["roe"] == 18.2
    assert rows[0]["or_yoy"] == 20.5
    assert rows[0]["netprofit_yoy"] == 22.0


def test_baostock_basic_and_daily_aliases_are_unified():
    basic = normalize_basic_records([{"code": "sh.600519", "code_name": "贵州茅台",
                                      "ipoDate": "2001-08-27", "industry": "白酒"}])
    daily = normalize_daily_records([{"date": "2026-01-05", "close": 10.0, "volume": 900,
                                      "amount": 9000.0, "pctChg": 1.5}])

    assert basic[0]["name"] == "贵州茅台"
    assert basic[0]["list_date"] == "2001-08-27"
    assert daily[0]["vol"] == 900
    assert daily[0]["pct_chg"] == 1.5


def test_trade_calendar_fields_are_unified_across_vendors():
    """交易日历字段必须统一，新鲜度门禁才能用真实交易日计数。"""
    from finance_agent.infrastructure.market_data.normalization import normalize_trade_cal_records

    vendor_a = normalize_trade_cal_records({
        "data": [{"cal_date": "20260911", "is_open": 1}, {"cal_date": "20260912", "is_open": 0}],
    })
    baostock = normalize_trade_cal_records([{"calendar_date": "2026-09-11", "is_trading_day": "1"}])

    assert vendor_a["data"][0]["cal_date"] == "2026-09-11"
    assert vendor_a["data"][0]["is_open"] == 1
    assert baostock[0]["cal_date"] == "2026-09-11"
    assert baostock[0]["is_open"] == "1"


# ── 生产取数 → 研究评分端到端回归 ─────────────────────────────────


class StubAkshare:
    """用中文列模拟 AKShare 的真实返回形态。

    行情日期以“今天”结尾，使新鲜度门禁在任何运行日期下都成立；抓取时刻由
    工具层的 Provider 元数据提供，无需在桩里伪造。
    """

    @staticmethod
    def stock_zh_a_hist(symbol, period, start_date, end_date, adjust):
        import pandas as pd

        closes = [round(10.0 * 1.004 ** index, 4) for index in range(120)]
        frame = pd.DataFrame({
            "日期": pd.date_range(end=pd.Timestamp.today().normalize(), periods=120).date,
            "股票代码": symbol,
            "开盘": closes,
            "收盘": closes,
            "最高": [close * 1.01 for close in closes],
            "最低": [close * 0.99 for close in closes],
            "成交量": [1000] * 120,
            "成交额": [10000.0] * 120,
            "振幅": [1.0] * 120,
            "涨跌幅": [0.4] * 120,
            "涨跌额": [0.04] * 120,
            "换手率": [1.0] * 120,
        })
        return frame

    @staticmethod
    def stock_financial_analysis_indicator(symbol):
        import pandas as pd

        return pd.DataFrame({
            "日期": pd.to_datetime(["2025-06-30", "2026-06-30"]).date,
            "净资产收益率(%)": [16.0, 18.0],
            "主营业务收入增长率(%)": [15.0, 20.0],
            "净利润增长率(%)": [12.0, 20.0],
        })

    @staticmethod
    def stock_info_a_code_name():
        import pandas as pd

        return pd.DataFrame({"code": ["600519"], "name": ["贵州茅台"]})


@pytest.fixture
def akshare_only_provider(monkeypatch):
    """构造只启用 AKShare 的 ProviderManager，并把它注入工具层。"""
    provider = AkshareDataSource()
    provider.ak = StubAkshare()
    manager = ProviderManager(providers={"akshare": provider}, order=["akshare"])
    monkeypatch.setattr(
        "finance_agent.domains.research.expert.stockdata.get_provider_manager",
        lambda: manager,
    )
    return manager


def test_akshare_shaped_records_produce_non_empty_research_scores(akshare_only_provider):
    """回归 P0：真实生产取数必须能生成规则引擎需要的三项评分。

    AKShare 是默认优先级最高的数据源，且不提供日估值接口。修复前
    中文列名使 K 线全部为空、估值缺失还会连累整条行情，真实请求因此
    恒定落入“数据不足”。
    """
    from finance_agent.domains.research.expert.stockdata import fetch_stock_data

    stock_data = fetch_stock_data(["600519"])
    entry = stock_data["600519"]

    assert entry["quote"]["price"] == entry["history"]["data"][-1]["close"]
    assert entry["quote"]["source"] == "akshare"
    assert entry["quote"]["adjustment"] == "raw"
    assert entry["indicators"]["roe"] == 18.0
    assert entry["indicators"]["or_yoy"] == 20.0

    class Gateway:
        def get_security_data(self, stock_code: str) -> dict:
            return stock_data[stock_code]

    request = AnalysisRequest(kind=AnalysisKind.SINGLE_STOCK, stock_codes=["600519"])
    snapshot, facts = SnapshotBuilder(Gateway()).build(request)
    indicators = snapshot.securities[0].indicators

    # AKShare 不提供日估值接口与披露日期，因此数据质量如实降级为 warning，
    # 但不能再是 critical_missing，也不能丢失评分。
    assert snapshot.quality.status == "warning"
    assert "valuation_metrics_missing" in snapshot.quality.warnings
    assert "fundamental_disclosure_date_missing" in snapshot.quality.warnings
    assert indicators["fundamental_score"] is not None
    assert indicators["technical_score"] is not None
    assert indicators["risk_score"] is not None
    assert RuleEngine.default().evaluate(snapshot, request).action.value != "数据不足"
    # 证据快照必须带完整原始输入、评估时点与逐项溯源，才可复算。
    assert facts[0].payload["inputs"]["history"]["data"]
    assert facts[0].payload["evaluated_at"]
    assert facts[0].payload["provenance"]["indicators"]["valuation_basis"] == "missing"


def test_quote_survives_unavailable_valuation_endpoint(monkeypatch):
    """估值接口不可用时行情本身必须保留，否则快照会判为关键数据缺失。"""
    from finance_agent.domains.research.expert import stockdata

    class DailyOnlyProvider:
        provider_name = "akshare"

        def is_available(self) -> bool:
            return True

        def get_daily(self, stock_code, start_date="", end_date="", adjustment="raw"):
            return [{"trade_date": "2026-08-28", "close": 12.5, "pct_chg": 0.4}]

        def get_daily_basic(self, stock_code, start_date="", end_date=""):
            raise RuntimeError("该数据源不支持日估值接口")

    manager = ProviderManager(providers={"akshare": DailyOnlyProvider()}, order=["akshare"])
    monkeypatch.setattr(stockdata, "get_provider_manager", lambda: manager)

    quote = stockdata._parse_json_dict(stockdata.get_stock_quote.invoke({"stock_code": "600519"}))

    assert quote["price"] == 12.5
    assert quote["pe"] is None
    # 来源必须来自成功的行情取数，而不是失败的估值取数。
    assert quote["source"] == "akshare"
