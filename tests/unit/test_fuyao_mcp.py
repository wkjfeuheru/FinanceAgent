"""同花顺 Fuyao MCP 适配器测试。

默认离线：所有用例都把 ``FuyaoMcpClient.call_tool`` 替换为内存假实现，
不访问网络。联网冒烟用例需 ``RUN_NETWORK_TESTS=1`` 且已配置 ``FUYAO_API_KEY``。
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import pytest

from finance_agent.infrastructure.market_data.fuyao_mcp import (
    FuyaoMcpClient,
    FuyaoMcpDataSource,
    FuyaoMcpError,
    _bars_to_daily,
    _from_ms,
    _index_thscode,
    _to_ms,
    _to_thscode,
)
from finance_agent.infrastructure.market_data.providers import UnsupportedProviderCapability


# ── 代码 / 时间格式换算 ──────────────────────────────────────

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("600519", "600519.SH"),
        ("000001", "000001.SZ"),
        ("920799", "920799.BJ"),
        ("600519.SH", "600519.SH"),
        ("sh600519", "600519.SH"),
        ("000001.SZ", "000001.SZ"),
    ],
)
def test_to_thscode(raw, expected):
    assert _to_thscode(raw) == expected


def test_to_thscode_rejects_legacy_bj():
    """已废止的北交所代码必须显式拒绝，不做猜测映射。"""
    with pytest.raises(UnsupportedProviderCapability):
        _to_thscode("830799")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("sh000001", "000001.SH"),
        ("sz399006", "399006.SZ"),
        ("上证指数", "000001.SH"),
        ("000300.SH", "000300.SH"),
    ],
)
def test_index_thscode(raw, expected):
    assert _index_thscode(raw) == expected


def test_ms_roundtrip_uses_china_timezone():
    """毫秒时间戳按 Asia/Shanghai 换算，日期不因时区偏移漂移。"""
    ms = _to_ms("2025-09-23")
    assert _from_ms(ms) == "2025-09-23"
    # 2025-09-23 00:00 Asia/Shanghai = UTC 2025-09-22 16:00
    assert datetime.fromtimestamp(ms / 1000, timezone.utc).date().isoformat() == "2025-09-22"


def test_from_ms_tolerates_garbage():
    assert _from_ms(None) is None
    assert _from_ms("not-a-number") is None


# ── K 线映射 ─────────────────────────────────────────────────

def test_bars_to_daily_maps_fields_and_computes_pct_change():
    items = [
        {"date_ms": _to_ms("2025-09-22"), "open_price": 10.0, "high_price": 11.0,
         "low_price": 9.5, "close_price": 10.0, "volume": 100.0, "turnover": 1000.0},
        {"date_ms": _to_ms("2025-09-23"), "open_price": 10.0, "high_price": 11.5,
         "low_price": 9.8, "close_price": 11.0, "volume": 200.0, "turnover": 2200.0},
    ]
    rows = _bars_to_daily(list(reversed(items)))  # 乱序输入应被排序

    assert [row["trade_date"] for row in rows] == ["2025-09-22", "2025-09-23"]
    assert rows[0]["open"] == 10.0 and rows[0]["close"] == 10.0
    assert rows[0]["vol"] == 100.0 and rows[0]["amount"] == 1000.0
    # 首行无前收，涨跌为空；次行按前收 10.0 → 11.0 计算。
    assert rows[0].get("pct_chg") is None
    assert rows[1]["change"] == 1.0
    assert rows[1]["pct_chg"] == pytest.approx(10.0)


# ── 信封解析 ─────────────────────────────────────────────────

def test_unwrap_success_returns_data():
    assert FuyaoMcpClient._unwrap('{"code": 0, "message": "success", "data": {"a": 1}}') == {"a": 1}


@pytest.mark.parametrize("code", [3001, 3002])
def test_unwrap_empty_codes_return_none(code):
    """标的不存在/数据未就绪视为空数据，触发降级而非熔断。"""
    assert FuyaoMcpClient._unwrap(f'{{"code": {code}, "message": "x", "data": null}}') is None


@pytest.mark.parametrize("code", [2001, 2003, 4001, 5001])
def test_unwrap_error_codes_raise(code):
    with pytest.raises(FuyaoMcpError) as exc:
        FuyaoMcpClient._unwrap(f'{{"code": {code}, "message": "boom", "data": null}}')
    assert exc.value.code == code


def test_unwrap_non_envelope_text_passes_through():
    assert FuyaoMcpClient._unwrap("plain text") == "plain text"


# ── 数据源：以假客户端驱动 ───────────────────────────────────

class FakeClient:
    """按工具名返回预设 data 的假 Fuyao 客户端。"""

    def __init__(self, responses: dict[str, Any], **kwargs: Any) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict]] = []
        self.base_url = "https://fuyao.aicubes.cn/mcp"
        self.api_key = "test-key"

    def call_tool(self, endpoint: str, name: str, **arguments: Any) -> Any:
        self.calls.append((endpoint, name, arguments))
        value = self.responses.get(name)
        return value(arguments) if callable(value) else value


def _source(responses: dict[str, Any]) -> tuple[FuyaoMcpDataSource, FakeClient]:
    data_source = FuyaoMcpDataSource.__new__(FuyaoMcpDataSource)
    client = FakeClient(responses)
    data_source.client = client
    return data_source, client


def test_get_daily_returns_normalized_ascending_records():
    data_source, client = _source({
        "get_a_share_prices_historical": {
            "item": [
                {"date_ms": _to_ms("2025-09-23"), "open_price": 1.0, "high_price": 2.0,
                 "low_price": 0.5, "close_price": 1.5, "volume": 10.0, "turnover": 15.0},
            ],
        },
    })

    rows = data_source.get_daily("600519", start_date="2025-09-01", end_date="2025-09-30")

    assert rows[-1]["trade_date"] == "2025-09-23"
    assert rows[-1]["close"] == 1.5
    endpoint, tool, args = client.calls[0]
    assert endpoint == "a-share" and tool == "get_a_share_prices_historical"
    assert args["thscode"] == "600519.SH"
    assert args["adjust"] == "none"  # raw
    assert isinstance(args["start"], int) and isinstance(args["end"], int)


def test_get_daily_rejects_unknown_adjustment():
    data_source, _ = _source({})
    with pytest.raises(UnsupportedProviderCapability):
        data_source.get_daily("600519", adjustment="split")


def test_get_daily_basic_maps_snapshot_fields():
    data_source, _ = _source({
        "get_a_share_valuations_snapshot": {
            "timestamp": _to_ms("2025-09-23"),
            "item": [{"thscode": "600519.SH", "name": "贵州茅台", "pe_ttm": 19.2,
                      "pe_mrq": 17.5, "pb_mrq": 6.2, "ps_ttm": 9.0}],
        },
    })

    rows = data_source.get_daily_basic("600519")

    assert rows[-1]["pe_ttm"] == 19.2
    assert rows[-1]["pe_lyr"] == 17.5
    assert rows[-1]["pb"] == 6.2
    assert rows[-1]["ps"] == 9.0
    assert rows[-1]["trade_date"] == "2025-09-23"


def test_get_daily_basic_all_null_returns_empty_for_fallback():
    data_source, _ = _source({
        "get_a_share_valuations_snapshot": {
            "timestamp": _to_ms("2025-09-23"),
            "item": [{"thscode": "600519.SH", "pe_ttm": None, "pe_mrq": None,
                      "pb_mrq": None, "ps_ttm": None}],
        },
    })
    assert data_source.get_daily_basic("600519") == []


def test_get_financial_indicator_flattens_abilities():
    from finance_agent.infrastructure.market_data.fuyao_mcp import _CHINA_TZ
    from finance_agent.domains.research.reporting_periods import recent_report_periods

    periods = recent_report_periods(datetime.now(_CHINA_TZ).date(), count=4)

    def indicators(args: dict[str, Any]) -> Any:
        # 对任意报告期都返回同一组能力，聚焦于拍平逻辑本身。
        return {
            "thscode": "600519.SH",
            "report": args.get("report"),
            "abilities": [
                {"ability": "growth", "indicators": [
                    {"index_id": "calculate_operating_income_yoy_growth_ratio", "value": "9.10"},
                    {"index_id": "calculate_parent_holder_net_profit_yoy_growth_ratio", "value": "8.89"},
                ]},
                {"ability": "profitability", "indicators": [
                    {"index_id": "index_weighted_avg_roe", "value": "17.89"},
                ]},
            ],
        }

    def income(_args: dict[str, Any]) -> Any:
        return {"item": [
            {
                "period_end_ms": _to_ms(f"{p[:4]}-{p[4:6]}-{p[6:]}"),
                "report_date_ms": _to_ms(f"{p[:4]}-{p[4:6]}-{p[6:]}"),
            }
            for p in periods
        ]}

    data_source, _ = _source({
        "get_a_share_financials_indicators": indicators,
        "get_a_share_financials_income_statements": income,
    })

    rows = data_source.get_financial_indicator("600519")

    # 升序 → 最近报告期在最后。
    assert len(rows) == 4
    latest = rows[-1]
    assert latest["roe"] == "17.89"
    assert latest["or_yoy"] == "9.10"
    assert latest["netprofit_yoy"] == "8.89"
    # 披露日从利润表按报告期回填（此处两者同值）。
    assert latest["ann_date"] == latest["end_date"]
    assert rows[0]["end_date"] < rows[-1]["end_date"]


def test_get_income_maps_period_dates_and_sorts_ascending():
    data_source, _ = _source({
        "get_a_share_financials_income_statements": {
            # Fuyao 按报告期降序返回；适配器须升序，使最后一行为最新一期。
            "item": [
                {"thscode": "600519.SH", "fiscal_year": 2025, "fiscal_period": "FY",
                 "period_end_ms": _to_ms("2025-12-31"), "report_date_ms": _to_ms("2026-04-01"),
                 "operating_income": 2.0},
                {"thscode": "600519.SH", "fiscal_year": 2024, "fiscal_period": "FY",
                 "period_end_ms": _to_ms("2024-12-31"), "report_date_ms": _to_ms("2025-04-01"),
                 "operating_income": 1.0},
            ],
        },
    })

    rows = data_source.get_income("600519")

    assert [row["period_end"] for row in rows] == ["2024-12-31", "2025-12-31"]
    assert rows[-1]["period_end"] == "2025-12-31"
    assert rows[-1]["report_date"] == "2026-04-01"


def test_get_trade_cal_filters_window():
    data_source, _ = _source({
        "get_a_share_calendar_trading_days": {
            "item": [
                {"date_ms": _to_ms("2025-09-22"), "date": "20250922"},
                {"date_ms": _to_ms("2025-09-23"), "date": "20250923"},
                {"date_ms": _to_ms("2025-09-24"), "date": "20250924"},
            ],
        },
    })

    rows = data_source.get_trade_cal("2025-09-23", "2025-09-23")

    assert [row["cal_date"] for row in rows] == ["2025-09-23"]
    assert rows[0]["is_open"] is True


def test_unsupported_capabilities_declared():
    """本源未声明的能力必须显式声明，交由降级链中的 AKShare 提供。"""
    data_source, _ = _source({})
    for method in (
        lambda: data_source.get_stock_basic(),
        data_source.get_market_breadth,
        data_source.get_margin_summary,
        data_source.get_northbound_holdings,
        data_source.get_policy_news,
    ):
        with pytest.raises(UnsupportedProviderCapability):
            method()


def test_is_available_requires_key_and_url():
    data_source = FuyaoMcpDataSource.__new__(FuyaoMcpDataSource)

    class _NoKey:
        api_key = ""
        base_url = "https://fuyao.aicubes.cn/mcp"

    class _Ok:
        api_key = "k"
        base_url = "https://fuyao.aicubes.cn/mcp"

    data_source.client = _NoKey()
    assert data_source.is_available() is False
    data_source.client = _Ok()
    assert data_source.is_available() is True


# ── 联网冒烟（默认跳过）─────────────────────────────────────

@pytest.mark.network
@pytest.mark.skipif(
    os.getenv("RUN_NETWORK_TESTS", "").strip().lower() not in {"1", "true", "yes", "on"}
    or not os.getenv("FUYAO_API_KEY", "").strip(),
    reason="需 RUN_NETWORK_TESTS=1 且配置 FUYAO_API_KEY",
)
def test_fuyao_live_daily_is_reachable():
    rows = FuyaoMcpDataSource().get_daily("600519", adjustment="forward")
    assert len(rows) >= 20
    assert rows[0]["trade_date"] < rows[-1]["trade_date"]
    assert float(rows[-1]["close"]) > 0
