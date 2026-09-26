"""可选联网冒烟测试：真实验证数据源可用性。

**默认不运行**——CI 与离线环境不应依赖第三方接口。启用方式：

```bash
RUN_NETWORK_TESTS=1 python -m pytest -q -m network
```

它验证的正是本次改动最容易在某台机器上静默失效的两条路径：K 线主路径（新浪源）
与日估值路径（东财 ``stock_value_em`` / BaoStock）。单元测试全部使用桩，无法发现
"接口被网络边缘过滤"这类环境问题——东财 K 线接口的故障就是这样藏了很久的。
"""

from __future__ import annotations

import os

import pytest

pytestmark = [
    pytest.mark.network,
    pytest.mark.skipif(
        os.getenv("RUN_NETWORK_TESTS", "").strip().lower() not in {"1", "true", "yes", "on"},
        reason="联网冒烟测试默认跳过；设置 RUN_NETWORK_TESTS=1 启用",
    ),
]


def test_akshare_forward_adjusted_daily_bars_are_reachable():
    """前复权 K 线主路径必须能取到，且按日期升序。"""
    from finance_agent.infrastructure.market_data.akshare_provider import AkshareDataSource

    rows = AkshareDataSource().get_daily("600519", adjustment="forward")

    assert len(rows) >= 200
    assert rows[0]["trade_date"] < rows[-1]["trade_date"]
    assert float(rows[-1]["close"]) > 0


def test_akshare_daily_valuation_is_reachable():
    """日估值必须能取到 PE(TTM)，且静态 PE 独立成键。"""
    from finance_agent.infrastructure.market_data.akshare_provider import AkshareDataSource

    latest = AkshareDataSource().get_daily_basic("600519")[-1]

    assert latest["trade_date"]
    assert latest["pe_ttm"] is not None
    assert latest["pb"] is not None
    # pe_lyr 允许为空（东财始终提供，但契约上不作保证）。
    assert "pe_lyr" in latest


def test_akshare_financial_indicator_returns_metrics():
    """财务指标必须非空：默认 start_year 会让该接口返回 0 行，使基本面评分退化。"""
    from finance_agent.infrastructure.market_data.akshare_provider import AkshareDataSource

    rows = AkshareDataSource().get_financial_indicator("600519")

    assert rows, "财务指标不得为空，否则基本面评分退化"
    latest = rows[-1]
    assert latest.get("end_date"), "必须带报告期"
    assert any(latest.get(key) is not None for key in ("roe", "or_yoy", "netprofit_yoy"))


def test_akshare_ann_date_is_backfilled_for_latest_period():
    """披露日必须回填到最新报告期，否则数据质量恒为 warning。"""
    from finance_agent.infrastructure.market_data.akshare_provider import AkshareDataSource

    latest = AkshareDataSource().get_financial_indicator("600519")[-1]

    assert latest.get("ann_date"), f"最新报告期 {latest.get('end_date')} 缺披露日"
    assert latest["ann_date"] >= latest["end_date"], "披露日不应早于报告期"


def test_akshare_stock_basic_carries_industry():
    """行业字段必须并入清单，否则行业关键词候选发现无从匹配。"""
    from finance_agent.infrastructure.market_data.akshare_provider import AkshareDataSource

    rows = AkshareDataSource().get_stock_basic()

    with_industry = [row for row in rows if str(row.get("industry") or "").strip()]
    assert len(with_industry) >= len(rows) * 0.9, "行业覆盖率应≥90%"
    maotai = next(row for row in rows if row.get("code") == "600519")
    assert maotai["industry"] == "白酒Ⅱ"


def test_baostock_valuation_agrees_with_akshare_on_magnitude():
    """两条估值路径互校。

    只比数量级，**不比精确相等**：复权锚点与更新时点不同，绝对差异是合法的；
    但这足以发现"某一路取到了完全不同的东西"（例如单位或口径错位）。
    """
    from finance_agent.infrastructure.market_data.akshare_provider import AkshareDataSource
    from finance_agent.infrastructure.market_data.baostock_provider import BaostockDataSource

    akshare_pe = float(AkshareDataSource().get_daily_basic("600519")[-1]["pe_ttm"])
    baostock_pe = float(BaostockDataSource().get_daily_basic("600519")[-1]["pe_ttm"])

    assert akshare_pe > 0 and baostock_pe > 0
    assert abs(akshare_pe - baostock_pe) / akshare_pe < 0.05


def test_beijing_exchange_is_rejected_by_baostock_and_served_by_akshare():
    """北交所：BaoStock 必须显式拒绝，AKShare 必须能服务现行 920 代码。"""
    from finance_agent.infrastructure.market_data.akshare_provider import AkshareDataSource
    from finance_agent.infrastructure.market_data.baostock_provider import BaostockDataSource
    from finance_agent.infrastructure.market_data.providers import UnsupportedProviderCapability

    with pytest.raises(UnsupportedProviderCapability):
        BaostockDataSource().get_daily("920799", adjustment="forward")

    rows = AkshareDataSource().get_daily("920799", adjustment="forward")
    assert rows and rows[-1]["trade_date"]


# ── 板块/概念（按主题找标的的唯一入口）────────────────────────────────────────
# 这条路径只挂在 *.push2.eastmoney.com 上，该域名在部分网络环境会连续数分钟 502/断连，
# 因此它必须纳入联网冒烟：本仓库自己的字段映射与主机轮换也要真实验证一次。

def test_board_list_reaches_eastmoney_and_contains_ai_theme():
    """概念板块表必须能取到，且含"人工智能"这类口语主题。"""
    from finance_agent.infrastructure.market_data.akshare_provider import AkshareDataSource

    rows = AkshareDataSource().get_board_list("concept")

    assert len(rows) >= 100, "概念板块表明显偏小，取数可能被截断"
    names = {row["name"] for row in rows}
    assert "人工智能" in names, f"概念板块表缺人工智能，样例：{sorted(names)[:20]}"
    ai = next(row for row in rows if row["name"] == "人工智能")
    assert ai["code"].startswith("BK")
    assert ai["change_pct"] is None or isinstance(ai["change_pct"], float)


def test_board_constituents_are_reachable_by_name():
    """板块名 → 代码 → 成分股：AI 主题必须能给出可评估的成分清单。"""
    from finance_agent.infrastructure.market_data.akshare_provider import AkshareDataSource

    provider = AkshareDataSource()
    rows = provider.get_board_constituents("人工智能", "concept")

    assert len(rows) >= 3, "人工智能板块成分不足，无法产出候选清单"
    assert all(row["code"] and row["name"] for row in rows)
    assert any(row.get("turnover_amount") for row in rows)
