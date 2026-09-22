"""模拟交易服务层：账户、商品、下单成交、持仓与账户口径的唯一实现。

设计约束（与仓库"不静默降级"原则一致）：

- **单一计算源**：REST 路由与 Agent 领域工具都调用本服务，因此"账户面板"
  与"对话里问我的持仓"不可能给出两个不同的数字。
- **只读与写入分离**：Agent 只调用 ``get_account`` / ``list_positions`` 等
  只读方法；下单/充值只能经 REST 进入。
- **价格缺失即失败**：取不到净值的商品直接抛 ``PricingUnavailableError``，
  不用成本价或 1.0 顶替成交。
- **资金操作幂等**：写操作接受 ``idempotency_key``，重复请求返回首次结果而
  不重复扣款，避免网络重试造成双花。
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Iterable

from finance_agent.config import (
    PORTFOLIO_MAX_DEPOSIT_AMOUNT,
    PORTFOLIO_MIN_ORDER_AMOUNT,
)
from finance_agent.portfolio.contracts import (
    AccountSnapshot,
    LiquidationResult,
    OrderView,
    PositionView,
    ProductView,
    SourcedValue,
    TradeResult,
    TransactionView,
)
from finance_agent.portfolio.errors import (
    InsufficientFundsError,
    InsufficientSharesError,
    InvalidAmountError,
    NoPositionError,
    PricingUnavailableError,
    ProductNotFoundError,
    ProductOfflineError,
)
from finance_agent.portfolio.fees import (
    redemption,
    round_money,
    round_shares,
    subscription_by_amount,
    subscription_by_shares,
)
from finance_agent.portfolio.pricing import (
    NavSource,
    require_nav,
)

logger = logging.getLogger(__name__)

SIMULATED_DISCLAIMER = "模拟交易数据，不构成投资建议。"


def _now() -> datetime:
    return datetime.now()


def _limitations(value: Any) -> list[str]:
    """jsonb 列可能返回 list，也可能返回 JSON 字符串；两种都要能读。"""
    if value is None:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _order_view(row: dict[str, Any], names: dict[str, str]) -> OrderView:
    return OrderView(
        order_id=str(row.get("order_id", "")),
        product_code=str(row.get("product_code", "")),
        product_name=names.get(str(row.get("product_code", "")), ""),
        side=str(row.get("side", "buy")),  # type: ignore[arg-type]
        shares=float(row.get("shares") or 0),
        price=float(row.get("price") or 0),
        gross_amount=float(row.get("gross_amount") or 0),
        fee=float(row.get("fee") or 0),
        net_amount=float(row.get("net_amount") or 0),
        realized_pnl=(
            float(row["realized_pnl"]) if row.get("realized_pnl") is not None else None
        ),
        fee_limitations=_limitations(row.get("fee_limitations")),
        created_at=row.get("created_at"),
    )


def _percent(numerator: float, denominator: float) -> float | None:
    """返回百分比数值（5.2 表示 5.2%）；分母非正时返回 ``None``。"""
    if not denominator:
        return None
    return round(numerator / denominator * 100.0, 4)


@dataclass
class PortfolioDeps:
    """可注入依赖；默认从模块级单例延迟构造，便于测试替换。"""

    store: Any = None
    library: Any = None
    nav_source: NavSource | None = None
    clock: Callable[[], datetime] = _now

    def build_store(self) -> Any:
        if self.store is not None:
            return self.store
        from finance_agent.data.portfolio_store import get_portfolio_store

        return get_portfolio_store()

    def build_library(self) -> Any:
        if self.library is not None:
            return self.library
        from finance_agent.data.product_library import get_product_library

        return get_product_library()

    def build_nav_source(self) -> NavSource:
        if self.nav_source is not None:
            return self.nav_source
        from finance_agent.portfolio.pricing import ProductLibraryNavSource

        return ProductLibraryNavSource(self.build_library())


class PortfolioService:
    """模拟交易业务逻辑。"""

    def __init__(self, deps: PortfolioDeps | None = None) -> None:
        self._deps = deps or PortfolioDeps()

    # ── 内部工具 ──────────────────────────────────────────────────

    @property
    def store(self) -> Any:
        return self._deps.build_store()

    @property
    def library(self) -> Any:
        return self._deps.build_library()

    @property
    def nav_source(self) -> NavSource:
        return self._deps.build_nav_source()

    def _names_for(self, codes: Iterable[str]) -> dict[str, str]:
        """批量取商品名；取不到时用空串，不影响数字口径。"""
        wanted = list(dict.fromkeys(str(code) for code in codes if str(code)))
        if not wanted:
            return {}
        try:
            products = self.library.query_by_codes(wanted)
        except Exception:  # noqa: BLE001 - 名称缺失不应让整个面板失败
            logger.warning("product_name_lookup_failed codes=%s", wanted)
            return {}
        names: dict[str, str] = {}
        for item in products:
            basic = item.get("basic_info") or {}
            code = str(basic.get("code") or "")
            if code:
                names[code] = str(basic.get("name") or "")
        return names

    def _product_or_raise(self, product_code: str) -> dict[str, Any]:
        code = str(product_code).strip()
        if not code:
            raise ProductNotFoundError("请提供商品代码")
        product = self.library.query_by_code(code)
        if product is None:
            raise ProductNotFoundError(f"商品 {code} 不存在")
        return product

    def _require_on_shelf(self, product: dict[str, Any]) -> None:
        """申购前置校验：下架商品不可买入。

        只在买入侧调用 —— 赎回必须对下架商品仍然放行，否则用户会被困在
        无法退出的持仓里。
        """
        basic = product.get("basic_info") or {}
        if not bool(basic.get("is_active", True)):
            raise ProductOfflineError(
                f"商品 {basic.get('code') or ''} 已下架，无法申购"
            )

    @staticmethod
    def _cash_of(account_row: dict[str, Any]) -> float:
        return float(account_row.get("cash_balance") or 0)

    # ── 商品（只读）──────────────────────────────────────────────

    def get_product(self, product_code: str) -> ProductView:
        """单个商品的货架视图。"""
        code = str(product_code).strip()
        product = self._product_or_raise(code)
        return self._to_product_view(code, product, self.nav_source.latest_nav(code))

    def list_products(
        self, product_type: str = "fund", *, include_inactive: bool = False,
    ) -> list[ProductView]:
        """商品货架。取不到净值的商品照常展示，但 ``tradable=False``。

        ``include_inactive=True`` 时连下架商品一并返回，仅供管理后台使用。
        """
        # 只在需要时传参：既有测试替身只实现了单参数形态的 list_products。
        summaries = (
            self.library.list_products(product_type, include_inactive=True)
            if include_inactive else self.library.list_products(product_type)
        )
        codes = [str(item.get("code")) for item in summaries]
        views: list[ProductView] = []
        for code in codes:
            try:
                product = self.library.query_by_code(code)
            except Exception:  # noqa: BLE001 - 单品读取失败不拖垮整个货架
                logger.warning("product_shelf_item_failed code=%s", code)
                continue
            if product is None:
                continue
            views.append(self._to_product_view(code, product, self.nav_source.latest_nav(code)))
        return views

    def _to_product_view(self, code: str, product: dict[str, Any], nav_quote: Any) -> ProductView:
        from finance_agent.portfolio.pricing import product_fee_rates

        basic = product.get("basic_info") or {}
        fee = product.get("fee") or {}
        performance = product.get("performance") or {}
        # 费率由 product_fee_rates 统一解析：产品库把费率列从 basic_info 里摘出到
        # fee 子字典，只读 basic_info 会一律读成"未披露"。
        subscription_rate, redemption_rate = product_fee_rates(product)
        limitations: list[str] = []
        if nav_quote is None:
            limitations.append("pricing_unavailable")
        if subscription_rate is None:
            limitations.append("fee_unavailable:subscription_fee")
        is_active = bool(basic.get("is_active", True))
        if not is_active:
            limitations.append("product_offline")
        return ProductView(
            code=code,
            name=str(basic.get("name") or ""),
            type=str(basic.get("type") or "fund"),
            risk_level=str(basic.get("risk_level") or ""),
            company=str(basic.get("company") or ""),
            manager=str(basic.get("manager") or ""),
            scale=basic.get("scale"),
            nav=SourcedValue(
                value=nav_quote.nav if nav_quote else None,
                source=nav_quote.source if nav_quote else "unavailable",
                as_of=nav_quote.as_of if nav_quote else "",
            ),
            return_1y=performance.get("return_1y"),
            max_drawdown=performance.get("max_drawdown"),
            sharpe_ratio=performance.get("sharpe_ratio"),
            # 前端按百分比展示，因此这里给百分比数值（1.5% → 1.5），
            # 与产品库以百分比存储 subscription_fee 的口径一致。
            subscription_fee=(
                round(subscription_rate * 100.0, 4) if subscription_rate is not None else None
            ),
            redemption_fee=str(fee.get("redemption_fee") or basic.get("redemption_fee") or ""),
            recommended_holding_period=str(basic.get("recommended_holding_period") or ""),
            investment_target=str(basic.get("investment_target") or ""),
            is_active=is_active,
            tradable=nav_quote is not None and is_active,
            limitations=limitations,
        )

    # ── 账户与持仓（只读）────────────────────────────────────────

    def list_positions(self, customer_id: str) -> list[PositionView]:
        """持仓明细，含按最新净值计算的市值与浮动盈亏。"""
        rows = self.store.list_positions(customer_id)
        if not rows:
            return []
        names = self._names_for(str(row.get("product_code")) for row in rows)
        priced: list[PositionView] = []
        for row in rows:
            code = str(row.get("product_code"))
            shares = float(row.get("shares") or 0)
            cost_amount = round_money(float(row.get("cost_amount") or 0))
            quote = self.nav_source.latest_nav(code)
            limitations: list[str] = []
            nav = quote.nav if quote else None
            if nav is None:
                limitations.append("pricing_unavailable")
            market_value = round_money(shares * nav) if nav is not None else None
            unrealized = (
                round_money(market_value - cost_amount) if market_value is not None else None
            )
            priced.append(PositionView(
                product_code=code,
                product_name=names.get(code, ""),
                shares=shares,
                cost_amount=cost_amount,
                avg_cost=float(row.get("avg_cost") or 0),
                nav=nav,
                nav_as_of=quote.as_of if quote else "",
                market_value=market_value,
                unrealized_pnl=unrealized,
                return_rate=_percent(unrealized, cost_amount) if unrealized is not None else None,
                opened_at=row.get("opened_at"),
                updated_at=row.get("updated_at"),
                pricing_status="priced" if nav is not None else "unavailable",
                limitations=limitations,
            ))

        total_value = sum(item.market_value or 0 for item in priced)
        if total_value > 0:
            priced = [
                item.model_copy(update={
                    "weight": round((item.market_value or 0) / total_value * 100.0, 4),
                })
                for item in priced
            ]
        return priced

    def get_account(self, customer_id: str) -> AccountSnapshot:
        """账户数据面板口径。

        任一持仓取不到净值时，把它登记进 ``pricing_issues`` 并置
        ``market_value_complete=False``，而不是把市值静默算小。
        """
        account_row = self.store.ensure_account(customer_id)
        positions = self.list_positions(customer_id)
        cash = round_money(self._cash_of(account_row))
        frozen = round_money(float(account_row.get("frozen_balance") or 0))
        market_value = round_money(sum(item.market_value or 0 for item in positions))
        position_cost = round_money(sum(item.cost_amount for item in positions))
        position_pnl = round_money(sum(item.unrealized_pnl or 0 for item in positions))
        total_deposit = round_money(float(account_row.get("total_deposit") or 0))
        realized = round_money(self.store.realized_pnl_total(customer_id))
        total_assets = round_money(cash + frozen + market_value)
        total_pnl = round_money(total_assets - total_deposit)
        issues = [
            f"{item.product_code}:{item.pricing_status}"
            for item in positions
            if item.pricing_status != "priced"
        ]
        return AccountSnapshot(
            customer_id=str(customer_id).upper(),
            cash_balance=cash,
            frozen_balance=frozen,
            market_value=market_value,
            total_assets=total_assets,
            total_deposit=total_deposit,
            total_pnl=total_pnl,
            total_pnl_pct=_percent(total_pnl, total_deposit),
            realized_pnl=realized,
            position_pnl=position_pnl,
            position_cost=position_cost,
            position_count=len(positions),
            market_value_complete=not issues,
            pricing_issues=issues,
            updated_at=account_row.get("updated_at"),
            simulated=True,
            disclaimer=SIMULATED_DISCLAIMER,
        )

    def find_order_by_key(self, customer_id: str, idempotency_key: str) -> OrderView | None:
        """按幂等键查找已成交委托（供前端/Agent 回放结果）。"""
        row = self.store.find_order_by_key(customer_id, idempotency_key)
        if row is None:
            return None
        names = self._names_for([str(row.get("product_code"))])
        return _order_view(row, names)

    def list_orders(self, customer_id: str, limit: int = 100) -> list[OrderView]:
        rows = self.store.list_orders(customer_id, limit)
        names = self._names_for(str(row.get("product_code")) for row in rows)
        return [_order_view(row, names) for row in rows]

    def list_transactions(self, customer_id: str, limit: int = 100) -> list[TransactionView]:
        rows = self.store.list_transactions(customer_id, limit)
        return [
            TransactionView(
                txn_id=str(row.get("txn_id", "")),
                kind=str(row.get("kind", "deposit")),  # type: ignore[arg-type]
                amount=float(row.get("amount") or 0),
                balance_after=float(row.get("balance_after") or 0),
                ref_id=str(row.get("ref_id") or ""),
                note=str(row.get("note") or ""),
                created_at=row.get("created_at"),
            )
            for row in rows
        ]

    # ── 充值 ─────────────────────────────────────────────────────

    def deposit(
        self, customer_id: str, amount: float, *, idempotency_key: str = "",
    ) -> tuple[TransactionView, AccountSnapshot, bool]:
        """充值虚拟资金。

        返回 ``(流水, 账户快照, 是否幂等重放)``。单笔上限为
        ``PORTFOLIO_MAX_DEPOSIT_AMOUNT``。
        """
        cid = str(customer_id).upper()
        value = round_money(float(amount))
        if value <= 0:
            raise InvalidAmountError("充值金额必须大于 0")
        if value > PORTFOLIO_MAX_DEPOSIT_AMOUNT:
            raise InvalidAmountError(
                f"单笔充值不得超过 {PORTFOLIO_MAX_DEPOSIT_AMOUNT:,.2f} 元"
            )

        self.store.ensure_account(cid)
        existing = self.store.find_transaction_by_key(cid, idempotency_key)
        if existing is not None:
            return self._transaction_view(existing), self.get_account(cid), True

        with self.store.transaction() as connection:
            cursor = connection.cursor()
            try:
                account = self.store.lock_account(cursor, cid)
                if account is None:
                    raise InvalidAmountError("账户不存在")
                balance = round_money(self._cash_of(account) + value)
                self.store.update_cash_balance(cursor, cid, balance)
                self.store.add_deposit(cursor, cid, value)
                inserted = self.store.insert_transaction(cursor, {
                    "txn_id": str(uuid.uuid4()),
                    "customer_id": cid,
                    "kind": "deposit",
                    "amount": value,
                    "balance_after": balance,
                    "ref_id": "",
                    "note": "模拟账户充值",
                    "idempotency_key": idempotency_key,
                })
            finally:
                cursor.close()

        return self._transaction_view(inserted), self.get_account(cid), False

    @staticmethod
    def _transaction_view(row: dict[str, Any]) -> TransactionView:
        return TransactionView(
            txn_id=str(row.get("txn_id", "")),
            kind=str(row.get("kind", "deposit")),  # type: ignore[arg-type]
            amount=float(row.get("amount") or 0),
            balance_after=float(row.get("balance_after") or 0),
            ref_id=str(row.get("ref_id") or ""),
            note=str(row.get("note") or ""),
            created_at=row.get("created_at"),
        )

    # ── 下单 ─────────────────────────────────────────────────────

    def buy(
        self,
        customer_id: str,
        product_code: str,
        *,
        amount: float | None = None,
        shares: float | None = None,
        idempotency_key: str = "",
    ) -> TradeResult:
        """按金额或份额申购。"""
        cid = str(customer_id).upper()
        if (amount is None) == (shares is None):
            raise InvalidAmountError("请且只能提供申购金额或申购份额其中之一")

        self.store.ensure_account(cid)
        replay = self._replay(cid, idempotency_key, product_code)
        if replay is not None:
            return replay

        product = self._product_or_raise(product_code)
        self._require_on_shelf(product)
        basic = product.get("basic_info") or {}
        name = str(basic.get("name") or "")
        quote = require_nav(self.nav_source, str(product_code).strip(), name)
        from finance_agent.portfolio.pricing import product_fee_rates

        subscription_rate, _ = product_fee_rates(product)

        if amount is not None:
            value = round_money(float(amount))
            if value < PORTFOLIO_MIN_ORDER_AMOUNT:
                raise InvalidAmountError(f"单笔申购金额不得低于 {PORTFOLIO_MIN_ORDER_AMOUNT:,.2f} 元")
            breakdown = subscription_by_amount(value, quote.nav, subscription_rate)
        else:
            wanted = round_shares(float(shares or 0))
            if wanted <= 0:
                raise InvalidAmountError("申购份额必须大于 0")
            breakdown = subscription_by_shares(wanted, quote.nav, subscription_rate)

        if breakdown.shares <= 0:
            raise InvalidAmountError("申购金额过低，不足以确认任何份额")

        with self.store.transaction() as connection:
            cursor = connection.cursor()
            try:
                account = self.store.lock_account(cursor, cid)
                if account is None:
                    raise InvalidAmountError("账户不存在")
                balance = self._cash_of(account)
                if balance < breakdown.cash_out:
                    raise InsufficientFundsError(
                        f"可用资金不足：需 {breakdown.cash_out:,.2f} 元，"
                        f"当前可用 {balance:,.2f} 元"
                    )
                position = self.store.get_position_row(cursor, cid, str(product_code).strip())
                old_shares = float(position.get("shares") or 0) if position else 0.0
                old_cost = round_money(float(position.get("cost_amount") or 0)) if position else 0.0
                new_shares = round_shares(old_shares + breakdown.shares)
                # 成本含费：成交的实际现金支出计入持仓成本，浮动盈亏因此是保守口径。
                new_cost = round_money(old_cost + breakdown.cash_out)
                new_balance = round_money(balance - breakdown.cash_out)

                self.store.upsert_position(cursor, cid, str(product_code).strip(), new_shares, new_cost)
                self.store.update_cash_balance(cursor, cid, new_balance)
                inserted = self.store.insert_order(cursor, {
                    "order_id": str(uuid.uuid4()),
                    "customer_id": cid,
                    "product_code": str(product_code).strip(),
                    "side": "buy",
                    "shares": breakdown.shares,
                    "price": quote.nav,
                    "gross_amount": breakdown.invested,
                    "fee": breakdown.fee,
                    "net_amount": breakdown.cash_out,
                    "realized_pnl": None,
                    "fee_limitations": breakdown.limitations,
                    "idempotency_key": idempotency_key,
                })
                self.store.insert_transaction(cursor, {
                    "txn_id": str(uuid.uuid4()),
                    "customer_id": cid,
                    "kind": "buy",
                    "amount": round_money(-breakdown.cash_out),
                    "balance_after": new_balance,
                    "ref_id": str(product_code).strip(),
                    "note": f"申购 {name}".strip(),
                    "idempotency_key": "",
                })
            finally:
                cursor.close()

        return self._result(cid, inserted, str(product_code).strip())

    def sell(
        self,
        customer_id: str,
        product_code: str,
        *,
        shares: float | None = None,
        all_shares: bool = False,
        idempotency_key: str = "",
    ) -> TradeResult:
        """按份额赎回；``all_shares=True`` 时清空该商品全部持仓。"""
        cid = str(customer_id).upper()
        code = str(product_code).strip()
        if not all_shares and shares is None:
            raise InvalidAmountError("请提供赎回份额或指定全部赎回")

        self.store.ensure_account(cid)
        replay = self._replay(cid, idempotency_key, code)
        if replay is not None:
            return replay

        product = self._product_or_raise(code)
        basic = product.get("basic_info") or {}
        name = str(basic.get("name") or "")
        quote = require_nav(self.nav_source, code, name)
        from finance_agent.portfolio.pricing import product_fee_rates

        _, redemption_rate = product_fee_rates(product)

        with self.store.transaction() as connection:
            cursor = connection.cursor()
            try:
                account = self.store.lock_account(cursor, cid)
                if account is None:
                    raise InvalidAmountError("账户不存在")
                position = self.store.get_position_row(cursor, cid, code)
                held = float(position.get("shares") or 0) if position else 0.0
                if held <= 0 or position is None:
                    raise NoPositionError(f"没有 {name or code} 的持仓")

                if all_shares:
                    wanted = held
                else:
                    wanted = round_shares(float(shares or 0))
                    if wanted <= 0:
                        raise InvalidAmountError("赎回份额必须大于 0")
                    if wanted > held:
                        raise InsufficientSharesError(
                            f"持仓份额不足：需 {wanted} 份，当前持有 {held} 份"
                        )

                held_cost = round_money(float(position.get("cost_amount") or 0))
                # 移动加权：按份额比例结转成本，而不是用平均成本乘份额，
                # 避免四舍五入在多次部分赎回后留下残余成本。
                if wanted >= held:
                    cost_out = held_cost
                else:
                    cost_out = round_money(held_cost * (wanted / held))

                breakdown = redemption(wanted, quote.nav, redemption_rate)
                realized = round_money(breakdown.cash_in - cost_out)
                remaining_shares = round_shares(held - wanted)
                remaining_cost = round_money(held_cost - cost_out)
                if remaining_shares <= 0:
                    remaining_shares, remaining_cost = 0.0, 0.0
                balance = round_money(self._cash_of(account) + breakdown.cash_in)

                self.store.upsert_position(cursor, cid, code, remaining_shares, remaining_cost)
                self.store.update_cash_balance(cursor, cid, balance)
                inserted = self.store.insert_order(cursor, {
                    "order_id": str(uuid.uuid4()),
                    "customer_id": cid,
                    "product_code": code,
                    "side": "sell",
                    "shares": wanted,
                    "price": quote.nav,
                    "gross_amount": breakdown.gross,
                    "fee": breakdown.fee,
                    "net_amount": breakdown.cash_in,
                    "realized_pnl": realized,
                    "fee_limitations": breakdown.limitations,
                    "idempotency_key": idempotency_key,
                })
                self.store.insert_transaction(cursor, {
                    "txn_id": str(uuid.uuid4()),
                    "customer_id": cid,
                    "kind": "sell",
                    "amount": breakdown.cash_in,
                    "balance_after": balance,
                    "ref_id": code,
                    "note": f"赎回 {name}".strip(),
                    "idempotency_key": "",
                })
            finally:
                cursor.close()

        return self._result(cid, inserted, code)

    def liquidate_all(self, customer_id: str) -> LiquidationResult:
        """一键清仓：逐个商品全额赎回。

        单个商品失败（例如净值缺失）只登记到 ``failed``，不中断其余商品的清仓，
        也不伪造成交。
        """
        cid = str(customer_id).upper()
        positions = self.store.list_positions(cid)
        orders: list[OrderView] = []
        cleared: list[str] = []
        failed: dict[str, str] = {}
        for row in positions:
            code = str(row.get("product_code"))
            try:
                outcome = self.sell(cid, code, all_shares=True)
                orders.append(outcome.order)
                cleared.append(code)
            except PricingUnavailableError as exc:
                failed[code] = exc.code
            except Exception as exc:  # noqa: BLE001 - 逐项隔离，其余持仓继续清仓
                logger.warning("liquidate_failed code=%s error=%s", code, exc)
                failed[code] = getattr(exc, "code", "portfolio_error")
        return LiquidationResult(
            orders=orders,
            cleared_codes=cleared,
            failed=failed,
            total_cash_in=round_money(sum(item.net_amount for item in orders)),
            total_realized_pnl=round_money(
                sum(item.realized_pnl or 0 for item in orders)
            ),
            account=self.get_account(cid),
        )

    # ── 结果装配 ─────────────────────────────────────────────────

    def _replay(
        self, customer_id: str, idempotency_key: str, product_code: str,
    ) -> TradeResult | None:
        """同一幂等键重复下单时，直接回放首次成交，不重复扣款。"""
        if not idempotency_key:
            return None
        row = self.store.find_order_by_key(customer_id, idempotency_key)
        if row is None:
            return None
        return self._result(customer_id, row, str(row.get("product_code") or product_code), replay=True)

    def _result(
        self, customer_id: str, order_row: dict[str, Any], product_code: str,
        *, replay: bool = False,
    ) -> TradeResult:
        """用刚写入的委托行装配结果；账户与持仓取提交后的最新值。"""
        code = str(product_code).strip()
        names = self._names_for([code])
        position = next(
            (
                item for item in self.list_positions(customer_id)
                if item.product_code == code
            ),
            None,
        )
        return TradeResult(
            order=_order_view(order_row, names),
            account=self.get_account(customer_id),
            position=position,
            idempotent_replay=replay,
        )


_service: PortfolioService | None = None


def get_portfolio_service() -> PortfolioService:
    """返回唯一的模拟交易服务实例。"""
    global _service
    if _service is None:
        _service = PortfolioService()
    return _service


__all__ = [
    "PortfolioDeps",
    "PortfolioService",
    "SIMULATED_DISCLAIMER",
    "get_portfolio_service",
]
