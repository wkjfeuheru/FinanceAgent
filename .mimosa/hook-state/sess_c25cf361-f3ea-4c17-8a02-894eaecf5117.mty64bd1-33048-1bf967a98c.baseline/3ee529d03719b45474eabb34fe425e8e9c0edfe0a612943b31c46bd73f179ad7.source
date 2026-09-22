"""AKShare 日估值取数的回归测试。

关键回归点：``get_daily_basic`` 曾无条件抛 ``UnsupportedProviderCapability``，
而它的依据（文档里那句"AKShare 不提供日估值接口"）引用的 ``stock_a_indicator_lg``
已从 AKShare 1.18.94 中删除。本文件确保估值真的取得到，**并且真的进入了评分**。
"""

from __future__ import annotations

import pytest

from finance_agent.data.akshare_provider import AkshareDataSource
from finance_agent.data.providers import ProviderUnavailableError, UnsupportedProviderCapability


def _frame():
    import pandas as pd

    return pd.DataFrame({
        "数据日期": ["2026-09-09", "2026-09-10", "2026-09-11"],
        "当日收盘价": [100.0, 101.0, 102.0],
        "总市值": [1.0e12, 1.01e12, 1.02e12],
        "流通市值": [8.0e11, 8.08e11, 8.16e11],
        "PE(TTM)": [19.0, 18.5, 18.0],
        "PE(静)": [21.0, 20.5, 20.0],
        "市净率": [2.1, 2.05, 2.0],
        "市销率": [3.0, 2.98, 2.95],
    })


class StubAkshare:
    """暴露 ``stock_value_em`` 的可控桩。"""

    def __init__(self, *, frame=None, error: Exception | None = None, expose: bool = True) -> None:
        self.calls: list[str] = []
        self._frame = frame if frame is not None else _frame()
        self._error = error
        if expose:
            self.stock_value_em = self._value_em

    def _value_em(self, symbol):
        self.calls.append(symbol)
        if self._error is not None:
            raise self._error
        return self._frame


@pytest.fixture
def provider() -> AkshareDataSource:
    return AkshareDataSource()


def test_daily_valuation_splits_ttm_and_static_pe(provider):
    provider.ak = StubAkshare()

    rows = provider.get_daily_basic("600519")

    assert [row["trade_date"] for row in rows] == ["2026-09-09", "2026-09-10", "2026-09-11"]
    latest = rows[-1]
    assert latest["pe_ttm"] == 18.0
    assert latest["pe_lyr"] == 20.0, "静态 PE 必须独立保留，不能被 pe_ttm 吞掉"
    assert latest["pb"] == 2.0
    assert latest["total_mv"] == 1.02e12
    assert latest["circ_mv"] == 8.16e11


def test_valuation_is_actually_consumed_by_the_fundamental_score(provider):
    """本次缺口的根因断言：取到估值后，基本面分数必须**因此改变**。

    只比较"非空"是不够的——缺 PE/PB 时分数同样非空，只是由 3 个会计指标
    各占 1/3 平均而成，静默换掉了口径。
    """
    from finance_agent.research.scoring import build_scores

    provider.ak = StubAkshare()
    latest = provider.get_daily_basic("600519")[-1]
    accounting = {"roe": 18.0, "or_yoy": 20.0, "netprofit_yoy": 22.0}
    history = {"adjustment": "forward", "data": []}

    with_valuation, _ = build_scores(
        {**accounting, "pe_ttm": latest["pe_ttm"], "pb": latest["pb"]}, history,
    )
    without_valuation, _ = build_scores(accounting, history)

    assert with_valuation["fundamental_score"] is not None
    assert without_valuation["fundamental_score"] is not None
    assert with_valuation["fundamental_score"] != without_valuation["fundamental_score"], (
        "PE/PB 取到却没进入评分——这正是缺口能藏这么久的形态"
    )


def test_window_is_applied_client_side(provider):
    """stock_value_em 没有日期参数，窗口必须在适配器里裁剪。"""
    provider.ak = StubAkshare()

    compact = provider.get_daily_basic("600519", start_date="20260910", end_date="2026-09-11")
    assert [row["trade_date"] for row in compact] == ["2026-09-10", "2026-09-11"]

    upper = provider.get_daily_basic("600519", end_date="2026-09-10")
    assert [row["trade_date"] for row in upper] == ["2026-09-09", "2026-09-10"]


def test_repeated_request_is_served_from_cache(provider):
    stub = StubAkshare()
    provider.ak = stub

    first = provider.get_daily_basic("600519")
    second = provider.get_daily_basic("600519")

    assert stub.calls == ["600519"], "命中缓存时不得再次取数"
    assert second == first


def test_missing_interface_is_a_capability_gap(provider):
    """AKShare 版本过旧时应报能力缺口，而不是伪装成网络失败。"""
    provider.ak = StubAkshare(expose=False)

    with pytest.raises(UnsupportedProviderCapability):
        provider.get_daily_basic("600519")


def test_request_failure_is_reported_as_unavailable(provider):
    """取数失败必须与能力缺口区分，否则审计看不出是"不支持"还是"暂时故障"。"""
    provider.ak = StubAkshare(error=ConnectionError("Remote end closed connection"))

    with pytest.raises(ProviderUnavailableError):
        provider.get_daily_basic("600519")


def test_legacy_beijing_code_fails_before_any_request(provider):
    stub = StubAkshare()
    provider.ak = stub

    with pytest.raises(UnsupportedProviderCapability):
        provider.get_daily_basic("830799")

    assert stub.calls == []
