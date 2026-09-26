"""统一数据接口与 Provider 路由管理器。"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any, Callable

from finance_agent.infrastructure.settings import (
    AKSHARE_ENABLED,
    BAOSTOCK_ENABLED,
    DATA_PROVIDER_COOLDOWN,
    DATA_PROVIDER_FAILURE_THRESHOLD,
    DATA_PROVIDER_ORDER,
    DATA_PROVIDER_TIMEOUT,
    FUYAO_ENABLED,
)
from finance_agent.infrastructure.market_data.akshare_provider import AkshareDataSource
from finance_agent.infrastructure.market_data.baostock_provider import BaostockDataSource
from finance_agent.infrastructure.market_data.fuyao_mcp import FuyaoMcpDataSource
from finance_agent.infrastructure.market_data.providers import (
    ProviderError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    UnsupportedProviderCapability,
)

logger = logging.getLogger(__name__)


class ProviderManager:
    """按配置路由股票数据请求，并在 provider 之间自动降级。"""

    def __init__(
        self,
        providers: dict[str, Any] | None = None,
        order: list[str] | None = None,
        *,
        call_timeout: float | None = None,
        failure_threshold: int | None = None,
        cooldown: float | None = None,
    ) -> None:
        self.order = order or DATA_PROVIDER_ORDER
        self.providers = providers if providers is not None else self._build_providers()
        # 逐股取数是并行的，而 manager 是单例；来源元数据必须按线程隔离，
        # 否则一个线程的 last_metadata 会在另一个线程读取前被覆盖，导致来源错配。
        self._local = threading.local()
        # 数据源守门：akshare/baostock 内部大量请求不设超时，一个挂住的 socket
        # 会让整轮请求永久阻塞；连续失败的源还要短暂熔断，避免每轮都重新
        # 尝试已知故障源、把预算耗光。
        self._call_timeout = DATA_PROVIDER_TIMEOUT if call_timeout is None else call_timeout
        self._failure_threshold = (
            DATA_PROVIDER_FAILURE_THRESHOLD if failure_threshold is None else failure_threshold
        )
        self._cooldown = DATA_PROVIDER_COOLDOWN if cooldown is None else cooldown
        self._consecutive_failures: dict[str, int] = {}
        self._open_until: dict[str, float] = {}
        self._breaker_lock = threading.Lock()

    # ── 熔断 ──────────────────────────────────────────────────────

    def _circuit_open(self, name: str) -> bool:
        with self._breaker_lock:
            until = self._open_until.get(name, 0.0)
            if until <= 0:
                return False
            if time.monotonic() >= until:
                # 冷却结束：允许半开，重试一次；失败会立刻再次打开。
                self._open_until.pop(name, None)
                self._consecutive_failures.pop(name, None)
                return False
            return True

    def _record_success(self, name: str) -> None:
        with self._breaker_lock:
            self._consecutive_failures.pop(name, None)
            self._open_until.pop(name, None)

    def _record_failure(self, name: str) -> None:
        with self._breaker_lock:
            count = self._consecutive_failures.get(name, 0) + 1
            self._consecutive_failures[name] = count
            if self._failure_threshold > 0 and count >= self._failure_threshold:
                self._open_until[name] = time.monotonic() + self._cooldown
                logger.warning(
                    "数据源 %s 连续失败 %d 次，熔断 %.0fs", name, count, self._cooldown,
                )

    def _call_with_timeout(self, provider: Any, name: str, method: str, args: Any, kwargs: Any) -> Any:
        """在守门超时内调用 provider；超时抛 ``ProviderTimeoutError``。

        底层取数（akshare/baostock）普遍不设 socket 超时，无法从外部取消，
        因此用守护线程执行：超时后放弃等待该线程，而不是让整轮请求永久阻塞。
        泄漏的是一个终将自行结束（或随进程退出）的守护线程，代价远小于阻塞服务。
        """
        timeout = self._call_timeout
        target = getattr(provider, method)
        if timeout <= 0:
            return target(*args, **kwargs)

        result: dict[str, Any] = {}
        failure: dict[str, BaseException] = {}

        def invoke() -> None:
            try:
                result["value"] = target(*args, **kwargs)
            except BaseException as exc:  # noqa: BLE001 - 原样回传给调用线程判定
                failure["error"] = exc

        worker = threading.Thread(target=invoke, name=f"provider-{name}-{method}", daemon=True)
        worker.start()
        worker.join(timeout)
        if worker.is_alive():
            raise ProviderTimeoutError(f"{name}.{method} 超时（>{timeout:g}s）")
        if "error" in failure:
            raise failure["error"]
        return result.get("value")

    @property
    def last_metadata(self) -> dict[str, Any]:
        """返回**当前线程**最近一次数据请求的来源元数据。"""
        return getattr(self._local, "metadata", {})

    @last_metadata.setter
    def last_metadata(self, value: dict[str, Any]) -> None:
        self._local.metadata = value

    def _build_providers(self) -> dict[str, Any]:
        """按启用配置懒构造可用 provider，避免导入可选依赖失败。"""
        factories: dict[str, tuple[bool, Callable[[], Any]]] = {
            "fuyao_mcp": (FUYAO_ENABLED, FuyaoMcpDataSource),
            "akshare": (AKSHARE_ENABLED, AkshareDataSource),
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
        """按优先级调用 provider，失败或空结果时自动尝试下一个。

        ``unsupported`` 与 ``failures`` 必须分开记录：前者是"该源从未声明这个
        能力"，后者是真实故障。混在一起会让每次 AKShare 优先的估值请求都显示
        ``degraded``，审计时无法区分"不支持"与"暂时取不到"。
        """
        failures: list[dict[str, str]] = []
        unsupported: list[str] = []
        attempted: list[str] = []
        circuits_open: list[str] = []
        for name in self.order:
            provider = self.providers.get(name)
            if provider is None or not getattr(provider, "is_available", lambda: True)():
                continue
            if self._circuit_open(name):
                # 熔断中：直接跳过，不重复付超时代价。记录在独立字段，
                # 便于审计区分"没试"与"试了但失败"。
                circuits_open.append(name)
                logger.debug("数据源 %s 处于熔断冷却期，跳过 %s", name, method)
                continue
            attempted.append(name)
            try:
                result = self._call_with_timeout(provider, name, method, args, kwargs)
            except UnsupportedProviderCapability as exc:
                # 能力缺口不是故障，不计入熔断（否则能力不足的源会被误熔断）。
                unsupported.append(name)
                logger.debug("数据源 %s 未声明 %s：%s", name, method, exc)
                continue
            except Exception as exc:  # provider 边界统一处理第三方异常
                failures.append({"provider": name, "error": str(exc)})
                self._record_failure(name)
                logger.warning("数据源 %s.%s 失败: %s", name, method, exc)
                continue
            if result is None or result == [] or result == {}:
                # 空结果只触发降级，不计入熔断：它可能是"该标的确实没有数据"，
                # 而非数据源故障，按故障熔断会误伤后续其它标的的取数。
                failures.append({"provider": name, "error": "返回空数据"})
                logger.debug("数据源 %s.%s 返回空数据", name, method)
                continue
            self._record_success(name)
            self.last_metadata = {
                "source": getattr(provider, "provider_name", name),
                "requested_provider": self.order[0] if self.order else name,
                "degraded": bool(failures),
                "attempted": attempted,
                "failures": failures,
                "unsupported": unsupported,
                "circuits_open": circuits_open,
                "fetched_at": datetime.now().isoformat(),
            }
            return result
        self.last_metadata = {
            "source": None,
            "requested_provider": self.order[0] if self.order else None,
            "degraded": bool(failures),
            "attempted": attempted,
            "failures": failures,
            "unsupported": unsupported,
            "circuits_open": circuits_open,
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

    def get_index_daily(
        self,
        index_symbol: str,
        start_date: str = "",
        end_date: str = "",
    ) -> Any:
        """获取指数日线（指数符号须带市场前缀，如 ``sh000001``）。"""
        return self._call("get_index_daily", index_symbol, start_date, end_date)

    def get_market_breadth(self) -> Any:
        """获取市场宽度（涨跌家数/涨跌停/活跃度，最近交易日快照）。"""
        return self._call("get_market_breadth")

    def get_margin_summary(self) -> Any:
        """获取两市融资融券汇总（日频；金额单位：亿元）。"""
        return self._call("get_margin_summary")

    def get_northbound_holdings(self) -> Any:
        """获取北向持股市值（季度披露；金额单位：亿元）。"""
        return self._call("get_northbound_holdings")

    def get_policy_news(self) -> Any:
        """获取近期财经快讯（政策新闻候选；按时间倒序）。"""
        return self._call("get_policy_news")


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
