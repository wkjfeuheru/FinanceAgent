"""K 线取源、退避与落盘缓存的回归测试。

关键回归点：东财 ``stock_zh_a_hist`` 在部分网络环境下被按 URL 过滤，因此主路径
必须走新浪源；同时缓存不得让重复请求再次打网络，也不得跨测试复用。
"""

from __future__ import annotations

import pytest

from finance_agent.infrastructure.market_data import akshare_provider, quote_cache
from finance_agent.infrastructure.market_data.akshare_provider import AkshareDataSource
from finance_agent.infrastructure.market_data.providers import UnsupportedProviderCapability


def _frame(periods: int = 80):
    import pandas as pd

    closes = [round(10.0 * 1.004 ** index, 4) for index in range(periods)]
    return pd.DataFrame({
        "date": pd.date_range(end="2026-09-11", periods=periods).date,
        "open": closes,
        "high": [close * 1.01 for close in closes],
        "low": [close * 0.99 for close in closes],
        "close": closes,
        "volume": [1000] * periods,
        "amount": [10000.0] * periods,
        "outstanding_share": [1.0e9] * periods,
        "turnover": [1.0] * periods,
    })


class StubAkshare:
    """同时可暴露新浪与东财两个接口的可控桩。"""

    def __init__(
        self,
        *,
        sina_error: Exception | None = None,
        sina_frame=None,
        em_frame=None,
        expose_sina: bool = True,
        expose_em: bool = True,
    ) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self._sina_error = sina_error
        self._sina_frame = sina_frame if sina_frame is not None else _frame()
        self._em_frame = em_frame if em_frame is not None else _frame()
        if expose_sina:
            self.stock_zh_a_daily = self._sina
        if expose_em:
            self.stock_zh_a_hist = self._eastmoney

    def _sina(self, symbol, start_date, end_date, adjust):
        self.calls.append(("sina", symbol, adjust))
        if self._sina_error is not None:
            raise self._sina_error
        return self._sina_frame

    def _eastmoney(self, symbol, period, start_date, end_date, adjust):
        self.calls.append(("eastmoney", symbol, adjust))
        return self._em_frame


@pytest.fixture
def provider() -> AkshareDataSource:
    """构造真实适配器，仅替换内部 ak 句柄。"""
    return AkshareDataSource()


def test_daily_bars_come_from_sina_with_market_prefix(provider):
    stub = StubAkshare()
    provider.ak = stub

    rows = provider.get_daily("600519", adjustment="forward")

    assert stub.calls == [("sina", "sh600519", "qfq")]
    assert rows[-1]["trade_date"] == "2026-09-11"
    # 夹具把收盘价四舍五入到 4 位，断言必须用同一个口径。
    assert rows[-1]["close"] == pytest.approx(round(10.0 * 1.004 ** 79, 4))


def test_daily_bars_fall_back_to_eastmoney_after_retries(provider, monkeypatch):
    monkeypatch.setattr(akshare_provider, "_sleep", lambda seconds: None)
    stub = StubAkshare(sina_error=ConnectionError("Remote end closed connection"))
    provider.ak = stub

    rows = provider.get_daily("600519", adjustment="forward")

    assert [call[0] for call in stub.calls] == ["sina", "sina", "sina", "eastmoney"]
    assert stub.calls[-1] == ("eastmoney", "600519", "qfq")
    assert rows


def test_missing_sina_interface_goes_straight_to_fallback(provider):
    """桩或旧版 AKShare 没有新浪接口时，不应浪费重试与退避。"""
    stub = StubAkshare(expose_sina=False)
    provider.ak = stub

    provider.get_daily("600519", adjustment="forward")

    assert stub.calls == [("eastmoney", "600519", "qfq")]


def test_repeated_request_is_served_from_cache(provider):
    stub = StubAkshare()
    provider.ak = stub

    first = provider.get_daily("600519", adjustment="forward")
    calls_after_first = list(stub.calls)
    second = provider.get_daily("600519", adjustment="forward")

    assert stub.calls == calls_after_first, "命中缓存时不得再次取数"
    assert second == first


def test_cache_key_separates_adjustment_and_window(provider):
    stub = StubAkshare()
    provider.ak = stub

    provider.get_daily("600519", adjustment="forward")
    provider.get_daily("600519", adjustment="raw")
    provider.get_daily("600519", start_date="2024-01-01", adjustment="forward")

    assert len(stub.calls) == 3


def test_legacy_beijing_code_fails_before_any_request(provider):
    stub = StubAkshare()
    provider.ak = stub

    with pytest.raises(UnsupportedProviderCapability):
        provider.get_daily("830799", adjustment="forward")

    assert stub.calls == []


def test_unsupported_adjustment_is_rejected(provider):
    stub = StubAkshare()
    provider.ak = stub

    with pytest.raises(UnsupportedProviderCapability):
        provider.get_daily("600519", adjustment="total_return")

    assert stub.calls == []


def test_cache_roundtrip_expiry_and_missing_key():
    quote_cache.write("daily", ("k",), [{"close": 10.5}], ttl_seconds=60)
    assert quote_cache.read("daily", ("k",)) == [{"close": 10.5}]

    assert quote_cache.read("daily", ("k",), ttl_seconds=0) is None, "ttl=0 表示关闭缓存"
    assert quote_cache.read("daily", ("k",), ttl_seconds=-1) is None
    assert quote_cache.read("daily", ("absent",)) is None


def test_cache_serialises_numpy_scalars():
    """DataFrame.to_dict 产出 numpy 标量；序列化失败会让缓存静默永不生效。"""
    import numpy as np

    quote_cache.write("daily", ("numpy",), [{"close": np.float64(10.5), "vol": np.int64(100)}])

    assert quote_cache.read("daily", ("numpy",)) == [{"close": 10.5, "vol": 100}]


def test_cache_write_failure_is_not_fatal(monkeypatch):
    """缓存目录不可用时必须只记 warning，不能连累取数。

    不用 ``tmp_path``：本环境不允许写系统临时目录。这里把一个**文件**当作缓存
    目录，``mkdir`` 会抛 ``NotADirectoryError``（``OSError`` 子类），正好覆盖该分支。
    """
    from finance_agent.infrastructure import settings as config

    monkeypatch.setattr(config, "QUOTE_CACHE_DIR", __file__)

    quote_cache.write("daily", ("k",), [{"close": 1.0}])
    assert quote_cache.read("daily", ("k",)) is None
