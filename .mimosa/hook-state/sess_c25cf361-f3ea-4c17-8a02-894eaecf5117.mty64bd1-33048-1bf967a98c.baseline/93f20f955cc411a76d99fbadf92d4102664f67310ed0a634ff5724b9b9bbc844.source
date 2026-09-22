"""Provider Manager 统一路由与降级测试。

全部使用内存 Fake Provider，不访问真实网络或第三方数据源。
"""

from __future__ import annotations

from typing import Any

import pytest

from finance_agent.data.provider_manager import ProviderManager
from finance_agent.data.providers import ProviderUnavailableError, UnsupportedProviderCapability


class FakeProvider:
    """按需抛错/返回空/声明能力不支持的内存 Provider。"""

    provider_name = "fake"

    def __init__(self, name: str, *, error: Exception | None = None,
                 empty: bool = False, unsupported: list[str] | None = None,
                 daily: list[dict[str, Any]] | None = None):
        self.provider_name = name
        self._error = error
        self._empty = empty
        self._unsupported = set(unsupported or [])
        self.calls: list[tuple[str, tuple, dict]] = []
        self._daily = daily if daily is not None else [{"trade_date": "20260101", "close": 10.0}]

    def is_available(self) -> bool:
        return True

    def _run(self, method: str, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((method, args, kwargs))
        if self._error is not None:
            raise self._error
        if method in self._unsupported:
            raise UnsupportedProviderCapability(f"{self.provider_name} 不支持 {method}")
        if self._empty:
            return []
        if method == "get_daily":
            return self._daily
        return {"data": [{"name": self.provider_name}]}

    def get_daily(
        self,
        stock_code: str,
        start_date: str = "",
        end_date: str = "",
        adjustment: str = "raw",
    ) -> Any:
        return self._run(
            "get_daily", stock_code, start_date, end_date, adjustment=adjustment,
        )

    def get_stock_basic(self, stock_code: str = "") -> Any:
        return self._run("get_stock_basic", stock_code)

    def get_daily_basic(self, stock_code: str, start_date: str = "", end_date: str = "") -> Any:
        return self._run("get_daily_basic", stock_code, start_date, end_date)

    def get_financial_indicator(self, stock_code: str) -> Any:
        return self._run("get_financial_indicator", stock_code)

    def get_income(self, stock_code: str) -> Any:
        return self._run("get_income", stock_code)

    def get_trade_cal(self, start_date: str = "", end_date: str = "") -> Any:
        return self._run("get_trade_cal", start_date, end_date)


def _manager(providers: dict[str, Any], order: list[str]) -> ProviderManager:
    return ProviderManager(providers=providers, order=order)


def test_primary_provider_success_no_fallback():
    a = FakeProvider("akshare")
    b = FakeProvider("baostock")
    manager = _manager({"akshare": a, "baostock": b}, ["akshare", "baostock"])

    result = manager.get_daily("600519")

    assert a.calls and b.calls == []
    assert result == a._daily
    assert manager.last_metadata["source"] == "akshare"
    assert manager.last_metadata["degraded"] is False


def test_fallback_when_primary_raises():
    a = FakeProvider("akshare", error=RuntimeError("network down"))
    b = FakeProvider("baostock")
    manager = _manager({"akshare": a, "baostock": b}, ["akshare", "baostock"])

    result = manager.get_daily("600519")

    assert b.calls
    assert manager.last_metadata["source"] == "baostock"
    assert manager.last_metadata["degraded"] is True
    assert manager.last_metadata["failures"][0]["provider"] == "akshare"


def test_fallback_when_primary_returns_empty():
    a = FakeProvider("akshare", empty=True)
    b = FakeProvider("baostock")
    manager = _manager({"akshare": a, "baostock": b}, ["akshare", "baostock"])

    result = manager.get_daily("600519")
    assert result == b._daily


def test_fallback_on_unsupported_capability():
    a = FakeProvider("akshare", unsupported=["get_daily_basic"])
    b = FakeProvider("baostock")
    manager = _manager({"akshare": a, "baostock": b}, ["akshare", "baostock"])

    result = manager.get_daily_basic("600519")
    assert b.calls
    assert manager.last_metadata["source"] == "baostock"


def test_unsupported_capability_is_not_recorded_as_degradation():
    """能力缺口与真实失败必须分开记录。

    否则每次 AKShare 优先的估值请求都显示 ``degraded``，而实际上那只是
    "该源从未声明这个能力"——审计时无法区分"不支持"与"暂时取不到"。
    """
    a = FakeProvider("akshare", unsupported=["get_daily_basic"])
    b = FakeProvider("tushare_mcp")
    manager = _manager({"akshare": a, "tushare_mcp": b}, ["akshare", "tushare_mcp"])

    manager.get_daily_basic("600519")

    assert manager.last_metadata["source"] == "tushare_mcp"
    assert manager.last_metadata["unsupported"] == ["akshare"]
    assert manager.last_metadata["failures"] == []
    assert manager.last_metadata["degraded"] is False


def test_real_failure_still_marks_degradation():
    """区分能力缺口不能顺手把真实故障也降级掉。"""
    a = FakeProvider("akshare", error=RuntimeError("boom"))
    b = FakeProvider("baostock")
    manager = _manager({"akshare": a, "baostock": b}, ["akshare", "baostock"])

    manager.get_daily("600519")

    assert manager.last_metadata["degraded"] is True
    assert manager.last_metadata["failures"][0]["provider"] == "akshare"
    assert manager.last_metadata["unsupported"] == []


def test_all_providers_fail_raises_unified_error():
    a = FakeProvider("akshare", error=RuntimeError("boom"))
    b = FakeProvider("baostock", error=RuntimeError("boom"))
    manager = _manager({"akshare": a, "baostock": b}, ["akshare", "baostock"])

    with pytest.raises(ProviderUnavailableError):
        manager.get_daily("600519")
    assert manager.last_metadata["source"] is None


def test_unavailable_provider_skipped():
    class DownProvider(FakeProvider):
        def is_available(self) -> bool:
            return False

    down = DownProvider("tushare_mcp")
    up = FakeProvider("akshare")
    manager = _manager({"tushare_mcp": down, "akshare": up}, ["tushare_mcp", "akshare"])

    result = manager.get_daily("600519")
    assert down.calls == []
    assert up.calls
    assert manager.last_metadata["source"] == "akshare"


def test_manager_singleton_is_thread_safe(monkeypatch):
    """验证单例获取函数返回同一实例，且可被 monkeypatch 替换用于测试。"""
    from finance_agent.data import provider_manager as pm

    monkeypatch.setattr(pm, "_manager_instance", None)
    first = pm.get_provider_manager()
    second = pm.get_provider_manager()
    assert first is second


def test_quote_tool_marks_source_meta(monkeypatch):
    """端到端：工具层通过 Manager 取数时，返回结构带 source 元数据且字段兼容。"""
    import json

    from finance_agent.orchestrator.tools import stockdata

    provider = FakeProvider("akshare")
    manager = _manager({"akshare": provider}, ["akshare"])
    monkeypatch.setattr(stockdata, "get_provider_manager", lambda: manager)

    # 需要估值数据，否则 get_daily_basic 为空记录；FakeProvider 对非 daily 返回基础行
    raw = stockdata.get_stock_quote.invoke({"stock_code": "600519"})
    result = json.loads(raw)
    assert result["source"] == "akshare"
    assert result["code"] == "600519"


def test_history_tool_normalizes_and_tags_source(monkeypatch):
    import json

    from finance_agent.orchestrator.tools import stockdata

    provider = FakeProvider("akshare")
    manager = _manager({"akshare": provider}, ["akshare"])
    monkeypatch.setattr(stockdata, "get_provider_manager", lambda: manager)

    raw = stockdata.get_stock_history.invoke({"stock_code": "600519"})
    result = json.loads(raw)
    assert result["count"] == 1
    assert result["data"][0]["date"] == "20260101"
    assert result["source"] == "akshare"


def test_history_tool_requests_forward_adjusted_data(monkeypatch):
    """技术分析默认请求前复权日线，并把实际口径返回给上层。"""
    import json

    from finance_agent.orchestrator.tools import stockdata

    class AdjustedProvider(FakeProvider):
        def get_daily(
            self,
            stock_code: str,
            start_date: str = "",
            end_date: str = "",
            adjustment: str = "raw",
        ) -> Any:
            return self._run(
                "get_daily", stock_code, start_date, end_date, adjustment=adjustment,
            )

    provider = AdjustedProvider("akshare")
    manager = _manager({"akshare": provider}, ["akshare"])
    monkeypatch.setattr(stockdata, "get_provider_manager", lambda: manager)

    raw = stockdata.get_stock_history.invoke({"stock_code": "600519"})
    result = json.loads(raw)

    assert provider.calls[0][2]["adjustment"] == "forward"
    assert result["adjustment"] == "forward"


def test_tool_errors_when_no_provider_available(monkeypatch):
    from finance_agent.orchestrator.tools import stockdata

    manager = _manager({}, ["akshare", "baostock"])
    monkeypatch.setattr(stockdata, "get_provider_manager", lambda: manager)

    with pytest.raises(ProviderUnavailableError):
        stockdata.get_stock_history.invoke({"stock_code": "600519"})
