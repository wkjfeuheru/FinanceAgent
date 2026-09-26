"""临时端到端校验：用真实 PostgreSQL 跑通模拟交易存储层。

使用一次性的测试用户与测试商品，结束后按顺序清理，不改动既有 schema 与业务数据。
运行：python -m finance_agent.cli.verify_portfolio_live
"""
from __future__ import annotations

import argparse
import sys

from finance_agent.infrastructure.settings import get_postgres_connection_factory
from finance_agent.infrastructure.persistence.postgres.schema import PORTFOLIO_SCHEMA_SQL

TEST_USER = "CUST999901"
TEST_CODE = "T00001"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="运行 PostgreSQL 投资组合临时端到端校验")
    parser.parse_args(argv)

    factory = get_postgres_connection_factory()
    conn = factory()
    cursor = conn.cursor()
    try:
        cursor.execute(PORTFOLIO_SCHEMA_SQL)
        conn.commit()

        # 清理可能残留的上次失败运行。
        cursor.execute("DELETE FROM finance.users WHERE customer_id = %s", (TEST_USER,))
        cursor.execute("DELETE FROM finance.products WHERE code = %s", (TEST_CODE,))
        conn.commit()

        # 建一个一次性用户与商品（只写本功能需要的列）。
        cursor.execute(
            """INSERT INTO finance.users
               (customer_id, username, display_name, password_hash, salt, created_at)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (TEST_USER, "verify_tmp", "校验用户", "x", "y", "2026-09-16T00:00:00"),
        )
        cursor.execute(
            """INSERT INTO finance.products
               (code, name, type, subscription_fee, redemption_fee, risk_level)
               VALUES (%s, %s, 'fund', %s, %s, %s)""",
            (TEST_CODE, "校验用示例基金", 1.5, "0.5%", "R3 中风险"),
        )
        cursor.execute(
            """INSERT INTO finance.product_performance
               (product_code, nav, update_date) VALUES (%s, %s, %s)""",
            (TEST_CODE, 3.85, "2026-09-08"),
        )
        conn.commit()
        print(f"已创建一次性用户 {TEST_USER} 与商品 {TEST_CODE}")
    finally:
        cursor.close()
        conn.close()

    from finance_agent.application.portfolio_service import ProductLibraryNavSource
    from finance_agent.domains.portfolio.service import (
        PortfolioDeps,
        PortfolioService,
    )
    from finance_agent.infrastructure.persistence.postgres.registry import (
        get_portfolio_store,
        get_product_library,
    )

    # 净值来源必须与生产组合根一致：PortfolioDeps 不再自带默认实现，
    # 漏注入会在第一步「申购」就抛 RuntimeError，而不是回退到某个猜测价。
    library = get_product_library()
    service = PortfolioService(PortfolioDeps(
        store=get_portfolio_store(),
        library=library,
        nav_source=ProductLibraryNavSource(library),
    ))

    failures: list[str] = []

    def check(label: str, condition: bool, detail: str = "") -> None:
        mark = "OK  " if condition else "FAIL"
        print(f"[{mark}] {label}{(' — ' + detail) if detail else ''}")
        if not condition:
            failures.append(label)

    try:
        # 1. 充值
        txn, account, replay = service.deposit(TEST_USER, 100000.0, idempotency_key="live-dep")
        check("充值入账", account.cash_balance == 100000.0 and not replay, f"余额={account.cash_balance}")

        # 2. 幂等：同键重复充值不重复入账
        _t, account2, replay2 = service.deposit(TEST_USER, 100000.0, idempotency_key="live-dep")
        check("充值幂等", replay2 and account2.cash_balance == 100000.0, f"余额={account2.cash_balance}")

        # 3. 申购
        bought = service.buy(TEST_USER, TEST_CODE, amount=38500.0, idempotency_key="live-buy")
        check("申购成交", bought.order.shares > 0, f"份额={bought.order.shares} 费用={bought.order.fee}")
        check("申购扣款", bought.account.cash_balance < 100000.0, f"余额={bought.account.cash_balance}")

        # 4. 幂等：同键重复下单不重复扣款
        replay_buy = service.buy(TEST_USER, TEST_CODE, amount=38500.0, idempotency_key="live-buy")
        check("下单幂等", replay_buy.idempotent_replay and replay_buy.account.cash_balance == bought.account.cash_balance)

        # 5. 持仓与账户口径
        positions = service.list_positions(TEST_USER)
        check("持仓可读", len(positions) == 1 and positions[0].nav == 3.85, f"{positions}")
        acct = service.get_account(TEST_USER)
        check("账户口径完整", acct.market_value_complete is True)
        check(
            "总资产=现金+市值",
            abs(acct.total_assets - (acct.cash_balance + acct.market_value)) < 0.02,
            f"{acct.total_assets} vs {acct.cash_balance}+{acct.market_value}",
        )
        check("无定价缺口", acct.pricing_issues == [], f"{acct.pricing_issues}")

        # 6. 部分赎回
        sold = service.sell(TEST_USER, TEST_CODE, shares=positions[0].shares / 2)
        check("部分赎回", sold.position is not None and sold.position.shares < positions[0].shares)
        check("已实现盈亏有值", sold.order.realized_pnl is not None, f"{sold.order.realized_pnl}")

        # 7. 一键清仓
        result = service.liquidate_all(TEST_USER)
        check("清仓成功", result.cleared_codes == [TEST_CODE] and result.failed == {})
        check("清仓后无持仓", service.list_positions(TEST_USER) == [])
        check("清仓后市值为 0", service.get_account(TEST_USER).market_value == 0.0)

        # 8. 记录与流水
        check("成交记录落库", len(service.list_orders(TEST_USER)) >= 3,
              f"订单数={len(service.list_orders(TEST_USER))}")
        check("资金流水落库", len(service.list_transactions(TEST_USER)) >= 3)

        # 9. 注销级联：删除用户应连带清理本功能全部数据
        cursor_conn = factory()
        cur = cursor_conn.cursor()
        cur.execute("DELETE FROM finance.users WHERE customer_id = %s", (TEST_USER,))
        cursor_conn.commit()
        for table in ("accounts", "cash_transactions", "orders", "positions"):
            cur.execute(
                f"SELECT COUNT(*) FROM finance.{table} WHERE customer_id = %s",  # noqa: S608 - 固定表名
                (TEST_USER,),
            )
            count = cur.fetchone()[0]
            check(f"注销级联清理 {table}", count == 0, f"残留={count}")
        cur.close()
        cursor_conn.close()
    finally:
        conn = factory()
        cur = conn.cursor()
        cur.execute("DELETE FROM finance.users WHERE customer_id = %s", (TEST_USER,))
        cur.execute("DELETE FROM finance.products WHERE code = %s", (TEST_CODE,))
        conn.commit()
        cur.close()
        conn.close()
        print("已清理一次性数据")

    if failures:
        print(f"\n失败项：{failures}")
        return 1
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
