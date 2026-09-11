"""统一数据接口与 Provider 路由管理器。"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any, Callable

from finance_agent.config import (
    AKSHARE_ENABLED,
    BAOSTOCK_ENABLED,
    DATA_PROVIDER_ORDER,
    TUSHARE_ENABLED,
)
from finance_agent.data.akshare_provider import AkshareDataSource
from finance_agent.data.baostock_provider import BaostockDataSource
from finance_agent.data.providers import ProviderError, ProviderUnavailableError
from finance_agent.data.tushare_mcp import TushareMcpDataSource

logger = logging.getLogger(__name__)


class ProviderManager:
    """按配置路由股票数据请求，并在 provider 之间自动降级。"""

    def __init__(self, providers: dict[str, Any] | None = None, order: list[str] | None = None) -> None:
        self.order = order or DATA_PROVIDER_ORDER
        self.providers = providers if providers is not None else self._build_providers()
        self.last_metadata: dict[str, Any] = {}

    def _build_providers(self) -> dict[str, Any]:
        """按启用配置懒构造可用 provider，避免导入可选依赖失败。"""
        factories: dict[str, tuple[bool, Callable[[], Any]]] = {
            "akshare": (AKSHARE_ENABLED, AkshareDataSource),
            "tushare_mcp": (TUSHARE_ENABLED, TushareMcpDataSource),
            "baostock": (BAOSTOCK_ENABLED, BaostockDataSource),
        }
        result = {}
        for name, (enabled, factory) in factories.items():
            if not enabled:
                continue
            try:
                provider = factory()
                if provider.is_available():
                    result[name] = provider
            except (ProviderError, ImportError, RuntimeError) as exc:
                logger.info("数据源 %s 不可用: %s", name, exc)
        return result

    def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        """按优先级调用 provider，失败或空结果时自动尝试下一个。"""
        failures: list[dict[str, str]] = []
        attempted: list[str] = []
        for name in self.order:
            provider = self.providers.get(name)
            if provider is None or not getattr(provider, "is_available", lambda: True)():
                continue
            attempted.append(name)
            try:
                result = getattr(provider, method)(*args, **kwargs)
                if result is None or result == [] or result == {}:
                    raise ProviderError("返回空数据")
                self.last_metadata = {
                    "source": getattr(provider, "provider_name", name),
                    "requested_provider": self.order[0] if self.order else name,
                    "degraded": bool(failures),
                    "attempted": attempted,
                    "failures": failures,
                    "fetched_at": datetime.now().isoformat(),
                }
                return result
            except Exception as exc:  # provider 边界统一处理第三方异常
                failures.append({"provider": name, "error": str(exc)})
                logger.warning("数据源 %s.%s 失败: %s", name, method, exc)
        self.last_metadata = {
            "source": None,
            "requested_provider": self.order[0] if self.order else None,
            "degraded": bool(failures),
            "attempted": attempted,
            "failures": failures,
            "fetched_at": datetime.now().isoformat(),
        }
        raise ProviderUnavailableError(f"所有可用数据源均无法执行 {method}: {failures}")

    def get_daily(
        self,
        stock_code: str,
        start_date: str = "",
        end_date: str = "",
        adjustment: str = "raw",
    ) -> Any:
        """获取指定复权口径的日线行情。"""
        return self._call("get_daily", stock_code, start_date, end_date, adjustment)

    def get_stock_basic(self, stock_code: str = "") -> Any:
        """获取股票基础信息。"""
        return self._call("get_stock_basic", stock_code)

    def get_daily_basic(self, stock_code: str, start_date: str = "", end_date: str = "") -> Any:
        """获取估值指标。"""
        return self._call("get_daily_basic", stock_code, start_date, end_date)

    def get_financial_indicator(self, stock_code: str) -> Any:
        """获取财务指标。"""
        return self._call("get_financial_indicator", stock_code)

    def get_income(self, stock_code: str) -> Any:
        """获取利润表。"""
        return self._call("get_income", stock_code)

    def get_trade_cal(self, start_date: str = "", end_date: str = "") -> Any:
        """获取交易日历。"""
        return self._call("get_trade_cal", start_date, end_date)


_manager_instance: ProviderManager | None = None
_manager_lock = threading.Lock()


def get_provider_manager() -> ProviderManager:
    """返回线程安全的 Provider Manager 单例。"""
    global _manager_instance
    if _manager_instance is None:
        with _manager_lock:
            if _manager_instance is None:
                _manager_instance = ProviderManager()
    return _manager_instance
