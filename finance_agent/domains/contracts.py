"""领域身份契约：业务领域枚举与稳定排序。

领域身份（有哪些领域、输出顺序）是**领域自身的属性**，因此定义在 ``domains``
侧；``domains`` 不得反向依赖 ``orchestration``。编排层通过 re-export 复用本模块，
使"新增领域"只需在领域侧登记一次（见 ``domains/registry.py``）。
"""

from __future__ import annotations

from enum import Enum


class BusinessDomain(str, Enum):
    STOCK_RESEARCH = "stock_research"
    PRODUCT_RESEARCH = "product_research"
    # 用户自有账户与持仓的只读问答；下单/充值只能走 REST，不经对话。
    ACCOUNT_PORTFOLIO = "account_portfolio"


#: 领域稳定排序：多领域路由与计划扇出按此顺序输出，保证结果确定。
#: 新增领域必须同步加入（``supervisor`` 以 ``.index`` 作排序键，缺失会 ValueError）。
DOMAIN_ORDER: tuple[BusinessDomain, ...] = (
    BusinessDomain.STOCK_RESEARCH,
    BusinessDomain.PRODUCT_RESEARCH,
    BusinessDomain.ACCOUNT_PORTFOLIO,
)


__all__ = ["BusinessDomain", "DOMAIN_ORDER"]
