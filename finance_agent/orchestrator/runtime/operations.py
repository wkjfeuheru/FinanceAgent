"""领域 operation 注册表：白名单、默认模式与模式解析器的唯一登记处。

每个业务领域的可用 operation、默认 mode 与 goal→mode 解析器此前分散在各
领域模块的 ``build_X_domain_graph`` 里，AdvisorSystem 按领域硬编码分发。
注册表把它们收敛为按 ``BusinessDomain`` 查询的单一数据源：

- 各领域 ``build_X_domain_graph`` 薄封装注册表条目（图构建口径不漂移）；
- ``AdvisorSystem._domain_runner`` 按注册表分发，不再维护 if/elif 领域表；
- 统一 Planner–Executor 的 ``react`` profile 从这里取得 operation 白名单，
  模型只能选择注册表内的 operation，不能自由调用领域工具。

注册表只登记**元数据与工厂**，不持有图实例：operation 的构建依赖
（如 StockDeps 的 QuantGateway）由 ``build(domain, deps=...)`` 现场注入，
避免模块级副作用与跨测试污染。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from finance_agent.orchestrator.contracts import BusinessDomain
from finance_agent.orchestrator.domains.base import DomainOperation, ModeResolver


@dataclass(frozen=True)
class DomainSpec:
    """一个业务领域的 operation 元数据（不含图实例）。"""

    domain: BusinessDomain
    operations_factory: Callable[..., list[DomainOperation]]
    default_mode: str
    mode_resolver: ModeResolver | None = None


def _stock_spec() -> DomainSpec:
    from finance_agent.orchestrator.domains.stock import (
        StockDeps,
        _resolve_stock_mode,
        default_stock_operations,
    )

    return DomainSpec(
        domain=BusinessDomain.STOCK_RESEARCH,
        operations_factory=lambda deps=None: default_stock_operations(deps or StockDeps()),
        default_mode="single_analysis",
        mode_resolver=_resolve_stock_mode,
    )


def _market_spec() -> DomainSpec:
    from finance_agent.orchestrator.domains.market import (
        _resolve_market_mode,
        default_market_operations,
    )

    return DomainSpec(
        domain=BusinessDomain.MARKET_INSIGHT,
        operations_factory=lambda deps=None: default_market_operations(deps),
        default_mode="market_overview",
        mode_resolver=_resolve_market_mode,
    )


def _product_spec() -> DomainSpec:
    from finance_agent.orchestrator.domains.product import (
        default_product_operations,
    )

    return DomainSpec(
        domain=BusinessDomain.PRODUCT_RESEARCH,
        operations_factory=lambda deps=None: default_product_operations(deps),
        default_mode="product_lookup",
        mode_resolver=None,
    )


def _account_spec() -> DomainSpec:
    from finance_agent.orchestrator.domains.account import (
        resolve_account_mode,
        default_account_operations,
    )

    return DomainSpec(
        domain=BusinessDomain.ACCOUNT_PORTFOLIO,
        operations_factory=lambda deps=None: default_account_operations(deps),
        default_mode="account_overview",
        mode_resolver=resolve_account_mode,
    )


class OperationRegistry:
    """按领域查询 operation 白名单的注册表（惰性构建，无模块级副作用）。"""

    def __init__(self, specs: Iterable[DomainSpec] | None = None) -> None:
        self._specs: dict[BusinessDomain, DomainSpec] = {}
        # ``specs=[]`` 是合法输入（空注册表），必须用 ``is None`` 判缺省，
        # 否则空列表会被当成"未提供"而装入默认领域。
        source = specs if specs is not None else (
            _stock_spec(), _market_spec(), _product_spec(), _account_spec(),
        )
        for spec in source:
            self.register(spec)

    def register(self, spec: DomainSpec) -> None:
        if spec.domain in self._specs:
            raise ValueError(f"duplicate domain registration: {spec.domain.value}")
        self._specs[spec.domain] = spec

    def spec(self, domain: BusinessDomain) -> DomainSpec:
        spec = self._specs.get(domain)
        if spec is None:
            raise KeyError(f"unregistered domain: {domain.value}")
        return spec

    def operations(self, domain: BusinessDomain, deps: Any = None) -> list[DomainOperation]:
        """构建该领域的 operation 白名单；``deps`` 现场注入构建依赖。"""
        return self.spec(domain).operations_factory(deps)

    def operation_names(self, domain: BusinessDomain) -> list[str]:
        return [operation.name for operation in self.operations(domain)]

    def modes(self, domain: BusinessDomain) -> list[str]:
        """该领域全部可被选中的模式（白名单模式的并集，按注册顺序）。"""
        seen: list[str] = []
        for operation in self.operations(domain):
            for mode in sorted(operation.modes):
                if mode not in seen:
                    seen.append(mode)
        return seen

    def resolve(self, domain: BusinessDomain, context: Any) -> str:
        """按该领域注册的解析器解析 mode；未注册解析器时返回默认模式。"""
        spec = self.spec(domain)
        if spec.mode_resolver is None:
            return spec.default_mode
        return spec.mode_resolver(context)

    def domains(self) -> list[BusinessDomain]:
        return list(self._specs)


_default_registry: OperationRegistry | None = None


def default_operation_registry() -> OperationRegistry:
    """进程级默认注册表；测试可用独立实例隔离。"""
    global _default_registry
    if _default_registry is None:
        _default_registry = OperationRegistry()
    return _default_registry


__all__ = [
    "DomainSpec",
    "OperationRegistry",
    "default_operation_registry",
]
