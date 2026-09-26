"""管理后台接口的请求/响应模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from finance_agent.domains.portfolio.contracts import AccountSnapshot, PositionView, ProductView


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


class ClearRecordsResponse(BaseModel):
    """清除对话记录的结果。"""

    status: str = "ok"
    cleared_keys: int = 0
    message: str = ""


class AdminProductUpsertRequest(BaseModel):
    """新增/编辑商品请求。

    上下架不在此处表达：``is_active`` 只能经 publish/offline 两个动作改变，
    避免"编辑商品"这类无关操作顺手把下架商品重新上架。

    ``nav`` 及 ``return_*`` / ``max_drawdown`` / ``volatility`` / ``sharpe_ratio``
    属于业绩区块（``finance.product_performance``），与商品静态字段一起提交；
    全部为 ``None`` 时不触碰业绩表，避免编辑商品顺手写进一条空净值。
    收益率一律是**小数**（``0.126`` 表示 12.6%），与产品库存储口径一致。
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

    # ── 业绩区块（可选）─────────────────────────────────────────
    #: 最新净值；必须为正 —— 非正净值会被取价逻辑判为不可用（无法成交）。
    nav: float | None = Field(default=None, gt=0, description="最新净值")
    #: 净值截止日期；写入 ``product_performance.update_date``。
    nav_date: str = Field(default="", max_length=32, description="净值日期")
    return_1m: float | None = Field(default=None, description="近一月收益（小数）")
    return_3m: float | None = Field(default=None, description="近三月收益（小数）")
    return_6m: float | None = Field(default=None, description="近六月收益（小数）")
    return_1y: float | None = Field(default=None, description="近一年收益（小数）")
    return_3y: float | None = Field(default=None, description="近三年收益（小数）")
    max_drawdown: float | None = Field(default=None, description="最大回撤（小数）")
    volatility: float | None = Field(default=None, description="波动率（小数）")
    sharpe_ratio: float | None = Field(default=None, description="夏普比率")


__all__ = [
    "ClearRecordsResponse",
    "AdminProductListResponse",
    "AdminProductUpsertRequest",
    "AdminUserEntry",
    "AdminUserListResponse",
    "AdminUserPortfolioResponse",
]
