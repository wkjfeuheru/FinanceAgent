"""管理后台接口的请求/响应模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from finance_agent.portfolio.contracts import AccountSnapshot, PositionView, ProductView


class AdminUserEntry(BaseModel):
    """管理后台用户列表中的一行（含账户概览）。"""

    customer_id: str
    username: str
    display_name: str = ""
    created_at: str = ""
    is_admin: bool = False
    #: 账户口径与用户端完全一致；账户读取失败时为 None，不伪造 0。
    account: AccountSnapshot | None = None


class AdminUserListResponse(BaseModel):
    """用户总览。"""

    users: list[AdminUserEntry] = Field(default_factory=list)
    simulated: bool = True


class AdminUserPortfolioResponse(BaseModel):
    """单个用户的账户与持仓明细。"""

    customer_id: str
    user: AdminUserEntry | None = None
    account: AccountSnapshot | None = None
    positions: list[PositionView] = Field(default_factory=list)
    simulated: bool = True


class AdminProductListResponse(BaseModel):
    """含下架商品在内的完整货架。"""

    products: list[ProductView] = Field(default_factory=list)
    simulated: bool = True


class AdminProductUpsertRequest(BaseModel):
    """新增/编辑商品请求。

    上下架不在此处表达：``is_active`` 只能经 publish/offline 两个动作改变，
    避免"编辑商品"这类无关操作顺手把下架商品重新上架。
    """

    code: str = Field(..., min_length=1, max_length=32, description="商品代码")
    name: str = Field(..., min_length=1, max_length=128, description="商品名称")
    type: str = Field(default="fund", max_length=16, description="商品类型")
    establish_date: str = Field(default="", max_length=32, description="成立日期")
    scale: float | None = Field(default=None, description="规模（亿元）")
    manager: str = Field(default="", max_length=64, description="基金经理")
    company: str = Field(default="", max_length=128, description="基金公司")
    management_fee: float | None = Field(default=None, description="管理费率（%）")
    custody_fee: float | None = Field(default=None, description="托管费率（%）")
    subscription_fee: float | None = Field(default=None, description="申购费率（%）")
    redemption_fee: str = Field(default="", max_length=64, description="赎回费率")
    risk_level: str = Field(default="", max_length=32, description="风险等级")
    recommended_holding_period: str = Field(default="", max_length=32, description="建议持有期")
    investment_target: str = Field(default="", description="投资目标")
    investment_strategy: str = Field(default="", description="投资策略")


__all__ = [
    "AdminProductListResponse",
    "AdminProductUpsertRequest",
    "AdminUserEntry",
    "AdminUserListResponse",
    "AdminUserPortfolioResponse",
]
