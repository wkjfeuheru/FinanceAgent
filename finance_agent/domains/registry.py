"""领域注册表：新增一个业务领域只需在此登记一处。

每个 ``DomainSpec`` 声明该领域的**身份与装配信息**：稳定顺序、system prompt 路径
与工具白名单工厂。编排层（supervisor 的排序、experts/registry 的专家装配）统一
从本表派生，避免"领域枚举 / 排序 / 提示词 / 工具"分散在多处而各自漂移。

边界说明：本表**只登记领域身份**，不含意图词汇（intent → domain 属路由概念，
留在 ``orchestration/routing/intent.py``）。提示词以包内相对路径声明，由
``shared.prompts.load_prompt`` 在装配时加载，保持提示词随 git 版本化。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from finance_agent.domains.contracts import DOMAIN_ORDER, BusinessDomain


@dataclass(frozen=True)
class DomainSpec:
    """单个领域的身位与装配信息。"""

    domain: BusinessDomain
    #: system prompt 的包内相对路径（相对 ``finance_agent/``）。
    prompt_path: str
    #: 工具白名单工厂（延迟导入实现，避免 import 期把 orchestration 拉进来）。
    tools: Callable[[], list[Any]]
    #: 领域整体不可用时的兜底文案。
    unavailable: str
    #: 领域私有的 ``assemble`` 工厂（``(ExpertSink, final_text) -> ExpertAssembly``）。
    #: 延迟导入（与 ``tools`` 同理）：只有需要领域级后置校验的领域才登记，默认用
    #: 编排层的通用实现。股票域用它强制"给结论必须经过确定性内核"。
    assemble: Callable[[], Any] | None = None


def _stock_tools() -> list[Any]:
    from finance_agent.domains.research.expert import stock_tools

    return stock_tools()


def _stock_assemble() -> Any:
    from finance_agent.domains.research.expert.assemble import stock_assemble

    return stock_assemble


def _market_tools() -> list[Any]:
    from finance_agent.domains.market.expert import market_tools

    return market_tools()


def _product_tools() -> list[Any]:
    from finance_agent.domains.products.expert import product_tools

    return product_tools()


def _account_tools() -> list[Any]:
    from finance_agent.domains.portfolio.expert import account_tools

    return account_tools()


#: 领域注册表（唯一事实源）。键集必须覆盖 ``BusinessDomain`` 全体。
DOMAIN_SPECS: dict[BusinessDomain, DomainSpec] = {
    BusinessDomain.STOCK_RESEARCH: DomainSpec(
        domain=BusinessDomain.STOCK_RESEARCH,
        prompt_path="domains/research/expert/prompts/system.md",
        tools=_stock_tools,
        unavailable="股票数据暂时无法生成，请稍后重试。",
        assemble=_stock_assemble,
    ),
    BusinessDomain.MARKET_INSIGHT: DomainSpec(
        domain=BusinessDomain.MARKET_INSIGHT,
        prompt_path="domains/market/expert/prompts/system.md",
        tools=_market_tools,
        unavailable="市场数据暂时无法生成，请稍后重试。",
    ),
    BusinessDomain.PRODUCT_RESEARCH: DomainSpec(
        domain=BusinessDomain.PRODUCT_RESEARCH,
        prompt_path="domains/products/expert/prompts/system.md",
        tools=_product_tools,
        unavailable="产品研究暂不可用，请稍后重试。",
    ),
    BusinessDomain.ACCOUNT_PORTFOLIO: DomainSpec(
        domain=BusinessDomain.ACCOUNT_PORTFOLIO,
        prompt_path="domains/portfolio/expert/prompts/system.md",
        tools=_account_tools,
        unavailable="账户数据暂不可用，请稍后在「账户」页面查看，或稍后重试。",
    ),
}

# 注册表与枚举/排序必须严格一致：漏登记会让某个领域既无提示词也无工具。
if set(DOMAIN_SPECS) != set(BusinessDomain):
    raise RuntimeError(
        "DOMAIN_SPECS 必须覆盖全部 BusinessDomain："
        f"MISSING={sorted(set(BusinessDomain) - set(DOMAIN_SPECS))} "
        f"UNKNOWN={sorted(set(DOMAIN_SPECS) - set(BusinessDomain))}"
    )
if tuple(spec.domain for spec in (DOMAIN_SPECS[d] for d in DOMAIN_ORDER)) != DOMAIN_ORDER:
    raise RuntimeError("DOMAIN_ORDER 与 DOMAIN_SPECS 的领域集合不一致")


__all__ = ["DOMAIN_ORDER", "DOMAIN_SPECS", "DomainSpec", "BusinessDomain"]
