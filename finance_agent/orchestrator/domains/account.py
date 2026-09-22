"""账户/持仓领域子图（第四个业务领域）。

**只读领域**：本模块只调用 ``PortfolioService`` 的查询方法（``get_account`` /
``list_positions``），结构上无法下单或充值 —— 交易必须经 ``/api/portfolio``
由用户显式操作完成。命中交易意图时返回固定引导文案而非执行，与既有输入守卫
（``_ACTION_MARKERS`` 拦截"帮我买/带我操作"）取向一致。

摘要由确定性数据拼装，不交给 LLM 生成，因此"对话里问我的持仓"与"账户面板"
永远给出同一组数字。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from finance_agent.orchestrator.contracts import BusinessDomain, DomainTaskContext
from finance_agent.orchestrator.domains.base import (
    DomainOperation,
    OperationResult,
    build_domain_graph,
    context_text,
    keyword_mode,
)

#: 命中交易词时返回固定引导，不在对话里执行任何资金操作。
TRADE_GUIDANCE = (
    "为保证资金安全，投顾对话不代客下单、不代办充值。"
    "请在「商品」页面完成申购，在「持仓」页面完成卖出或一键清仓，"
    "充值入口在「账户」页面。以上均为模拟交易，不构成投资建议。"
)

#: 账户数据不可用时的固定文案（不回传原始异常）。
ACCOUNT_UNAVAILABLE = "账户数据暂不可用，请稍后在「账户」页面查看，或稍后重试。"

_DISCLAIMER = "（模拟交易数据，不构成投资建议。）"

_MODE_KEYWORDS: dict[str, tuple[str, ...]] = {
    # 交易引导优先于查询：句中同时出现"持仓"和"清仓"时按交易处理更安全。
    "trade_guidance": (
        "买入", "买点", "买进", "申购", "加仓", "补仓",
        "卖出", "卖掉", "赎回", "清仓", "平仓", "止盈", "止损",
        "充值", "入金", "转账", "追加资金", "帮我买", "帮我卖", "带我操作",
    ),
    "position_query": (
        "持仓", "仓位", "持有", "重仓", "底仓", "股票池", "基金池",
        "持仓明细",
    ),
    "account_overview": (
        "账户", "资产", "总资产", "可用资金", "余额", "cash", "盈亏",
        "收益", "本金", "净值", "仓位比例",
        "亏了多少", "赚了多少", "收益率",
    ),
}

_DEFAULT_MODE = "account_overview"


def _money(value: Any) -> str:
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "—"


def _pct(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):+.2f}%"
    except (TypeError, ValueError):
        return "—"


@dataclass
class AccountDomainDeps:
    """账户领域依赖；``service`` 可注入以便测试。"""

    service: Any = None

    def build_service(self) -> Any:
        if self.service is not None:
            return self.service
        from finance_agent.portfolio.service import get_portfolio_service

        return get_portfolio_service()


def _account_payload(service: Any, customer_id: str) -> dict[str, Any]:
    snapshot = service.get_account(customer_id)
    return snapshot.model_dump(mode="json") if hasattr(snapshot, "model_dump") else dict(snapshot)


def _positions_payload(service: Any, customer_id: str) -> list[dict[str, Any]]:
    positions = service.list_positions(customer_id)
    return [
        item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
        for item in positions
    ]


def _account_overview(context: DomainTaskContext, service: Any) -> OperationResult:
    account = _account_payload(service, context.customer_id)
    lines = [
        f"可用资金 {_money(account.get('cash_balance'))} 元，"
        f"持仓市值 {_money(account.get('market_value'))} 元，"
        f"总资产 {_money(account.get('total_assets'))} 元。",
        f"累计充值 {_money(account.get('total_deposit'))} 元，"
        f"累计盈亏 {_money(account.get('total_pnl'))} 元"
        f"（{_pct(account.get('total_pnl_pct'))}）；"
        f"其中已实现盈亏 {_money(account.get('realized_pnl'))} 元，"
        f"浮动盈亏 {_money(account.get('position_pnl'))} 元。",
    ]
    limitations: list[str] = []
    if not account.get("market_value_complete", True):
        issues = "、".join(str(item) for item in account.get("pricing_issues", []) or [])
        lines.append(f"注意：部分持仓缺少可用净值（{issues}），市值口径不完整。")
        limitations.extend(f"pricing_issue:{item}" for item in account.get("pricing_issues", []) or [])
    if not account.get("position_count"):
        lines.append("当前没有持仓。")
    lines.append(_DISCLAIMER)
    return OperationResult(
        structured_data={"account": account, "mode": "account_overview"},
        summary="\n".join(lines),
        status="success" if account.get("market_value_complete", True) else "partial",
        limitations=limitations,
    )


def _position_query(context: DomainTaskContext, service: Any) -> OperationResult:
    positions = _positions_payload(service, context.customer_id)
    account = _account_payload(service, context.customer_id)
    if not positions:
        return OperationResult(
            structured_data={"account": account, "positions": [], "mode": "position_query"},
            summary=f"当前没有持仓，可用资金 {_money(account.get('cash_balance'))} 元。\n{_DISCLAIMER}",
            status="success",
        )

    lines = [f"当前持有 {len(positions)} 只商品："]
    for item in positions:
        name = str(item.get("product_name") or item.get("product_code") or "")
        code = str(item.get("product_code") or "")
        label = f"{name}（{code}）" if name else code
        if item.get("pricing_status") != "priced":
            lines.append(f"- {label}：{item.get('shares')} 份，暂时缺少可用净值，无法计算市值与盈亏。")
            continue
        lines.append(
            f"- {label}：{item.get('shares')} 份，"
            f"市值 {_money(item.get('market_value'))} 元，"
            f"浮动盈亏 {_money(item.get('unrealized_pnl'))} 元"
            f"（{_pct(item.get('return_rate'))}），"
            f"占比 {_pct(item.get('weight'))}。"
        )
    lines.append(
        f"持仓市值合计 {_money(account.get('market_value'))} 元，"
        f"占总资产 {_pct(_weight_of(account.get('market_value'), account.get('total_assets')))}。"
    )
    lines.append(_DISCLAIMER)

    limitations = [
        f"pricing_issue:{item.get('product_code')}"
        for item in positions
        if item.get("pricing_status") != "priced"
    ]
    return OperationResult(
        structured_data={"account": account, "positions": positions, "mode": "position_query"},
        summary="\n".join(lines),
        status="success" if not limitations else "partial",
        limitations=limitations,
    )


def _weight_of(market_value: Any, total_assets: Any) -> float | None:
    try:
        total = float(total_assets)
        if total <= 0:
            return None
        return round(float(market_value) / total * 100.0, 4)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _trade_guidance(context: DomainTaskContext, service: Any) -> OperationResult:
    """命中交易意图：不执行任何资金操作，返回固定引导。"""
    return OperationResult(
        structured_data={"mode": "trade_guidance", "executed": False},
        summary=TRADE_GUIDANCE,
        status="success",
    )


def _safe(handler: Callable[[DomainTaskContext, Any], OperationResult], service: Any):
    """把未预期异常收敛为固定安全文案，绝不回传原始异常文本。"""

    def wrapped(context: DomainTaskContext) -> OperationResult:
        try:
            return handler(context, service)
        except Exception:  # noqa: BLE001 - 失败只给固定文案，细节进日志
            import logging

            logging.getLogger(__name__).exception(
                "account_domain_failed customer_id=%s", context.customer_id,
            )
            return OperationResult(
                structured_data={"mode": "unavailable"},
                summary=ACCOUNT_UNAVAILABLE,
                status="failed",
                limitations=["account_service_failed"],
            )

    return wrapped


def default_account_operations(deps: AccountDomainDeps | None = None) -> list[DomainOperation]:
    deps = deps or AccountDomainDeps()
    service = deps.build_service()
    return [
        DomainOperation(
            name="account_overview",
            modes=frozenset({"account_overview"}),
            handler=_safe(_account_overview, service),
        ),
        DomainOperation(
            name="position_query",
            modes=frozenset({"position_query"}),
            handler=_safe(_position_query, service),
        ),
        DomainOperation(
            name="trade_guidance",
            modes=frozenset({"trade_guidance"}),
            handler=_safe(_trade_guidance, service),
        ),
    ]


def resolve_account_mode(context: DomainTaskContext) -> str:
    """按关键词确定模式；交易词优先，避免"清仓"被当成持仓查询。"""
    return keyword_mode(context_text(context), _MODE_KEYWORDS, _DEFAULT_MODE)


def build_account_domain_graph(operations=None, *, deps: AccountDomainDeps | None = None):
    """编译账户领域子图；白名单来自 operation 注册表（唯一事实源）。

    ``operations=[]`` 是合法输入（白名单为空），用 ``is None`` 判缺省。
    """
    from finance_agent.orchestrator.operations import default_operation_registry

    registry = default_operation_registry()
    return build_domain_graph(
        BusinessDomain.ACCOUNT_PORTFOLIO,
        default_account_operations(deps) if operations is None else operations,
        default_mode=registry.spec(BusinessDomain.ACCOUNT_PORTFOLIO).default_mode,
        mode_resolver=registry.spec(BusinessDomain.ACCOUNT_PORTFOLIO).mode_resolver,
    )


__all__ = [
    "ACCOUNT_UNAVAILABLE",
    "AccountDomainDeps",
    "TRADE_GUIDANCE",
    "build_account_domain_graph",
    "default_account_operations",
    "resolve_account_mode",
]
