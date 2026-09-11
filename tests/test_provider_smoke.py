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
    from finance_agent.data.akshare_provider import AkshareDataSource

    rows = AkshareDataSource().get_daily("600519", adjustment="forward")

    assert len(rows) >= 200
    assert rows[0]["trade_date"] < rows[-1]["trade_date"]
    assert float(rows[-1]["close"]) > 0


def test_akshare_daily_valuation_is_reachable():
    """日估值必须能取到 PE(TTM)，且静态 PE 独立成键。"""
    from finance_agent.data.akshare_provider import AkshareDataSource

    latest = AkshareDataSource().get_daily_basic("600519")[-1]

    assert latest["trade_date"]
    assert latest["pe_ttm"] is not None
    assert latest["pb"] is not None
    # pe_lyr 允许为空（东财始终提供，但契约上不作保证）。
    assert "pe_lyr" in latest


def test_baostock_valuation_agrees_with_akshare_on_magnitude():
    """两条估值路径互校。

    只比数量级，**不比精确相等**：复权锚点与更新时点不同，绝对差异是合法的；
    但这足以发现"某一路取到了完全不同的东西"（例如单位或口径错位）。
    """
    from finance_agent.data.akshare_provider import AkshareDataSource
    from finance_agent.data.baostock_provider import BaostockDataSource

    akshare_pe = float(AkshareDataSource().get_daily_basic("600519")[-1]["pe_ttm"])
    baostock_pe = float(BaostockDataSource().get_daily_basic("600519")[-1]["pe_ttm"])

    assert akshare_pe > 0 and baostock_pe > 0
    assert abs(akshare_pe - baostock_pe) / akshare_pe < 0.05


def test_beijing_exchange_is_rejected_by_baostock_and_served_by_akshare():
    """北交所：BaoStock 必须显式拒绝，AKShare 必须能服务现行 920 代码。"""
    from finance_agent.data.akshare_provider import AkshareDataSource
    from finance_agent.data.baostock_provider import BaostockDataSource
    from finance_agent.data.providers import UnsupportedProviderCapability

    with pytest.raises(UnsupportedProviderCapability):
        BaostockDataSource().get_daily("920799", adjustment="forward")

    rows = AkshareDataSource().get_daily("920799", adjustment="forward")
    assert rows and rows[-1]["trade_date"]
