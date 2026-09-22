"""账户/持仓领域子图测试：模式解析、确定性摘要与只读不变量。"""

from __future__ import annotations

import pytest

from finance_agent.orchestrator.contracts import (
    BusinessDomain,
    DomainTaskContext,
    PlanTask,
)
from finance_agent.orchestrator.domains.account import (
    TRADE_GUIDANCE,
    AccountDomainDeps,
    build_account_domain_graph,
    resolve_account_mode,
)
from finance_agent.orchestrator.supervisor_graph import _DOMAIN_ORDER, classify_domains

from tests.test_portfolio_service import (  # noqa: E402 - 复用服务层内存假件
    PRODUCTS,
    _FakeLibrary,
    _FakeNavSource,
    _FakeStore,
)

CUSTOMER = "CUST000001"


def _context(message: str) -> DomainTaskContext:
    return DomainTaskContext(
        task=PlanTask(
            task_id="t-1", domain=BusinessDomain.ACCOUNT_PORTFOLIO,
            goal=message, instruction=message, expected_output="domain_outcome",
        ),
        thread_id=f"v1:{CUSTOMER}:conv",
        customer_id=CUSTOMER,
        conversation_id="conv",
        user_message=message,
    )


@pytest.fixture()
def service():
    from finance_agent.portfolio.service import PortfolioDeps, PortfolioService

    return PortfolioService(PortfolioDeps(
        store=_FakeStore(),
        library=_FakeLibrary(PRODUCTS),
        nav_source=_FakeNavSource({"110011": 3.85, "003003": 1.0}),
    ))


def _run(service, message: str):
    graph = build_account_domain_graph(deps=AccountDomainDeps(service=service))
    return graph.invoke({"context": _context(message)})["domain_outcome"]


# ── 模式解析 ──────────────────────────────────────────────────────

@pytest.mark.parametrize("message,expected", [
    ("我的持仓怎么样", "position_query"),
    ("看看我的仓位", "position_query"),
    ("我持有几只基金", "position_query"),
    ("我的账户里还有多少钱", "account_overview"),
    ("我的总资产是多少", "account_overview"),
    ("我亏了多少", "account_overview"),
    ("帮我买 1000 块 110011", "trade_guidance"),
    ("我要清仓", "trade_guidance"),
    ("帮我充值 5000", "trade_guidance"),
    ("我想赎回易方达中小盘", "trade_guidance"),
])
def test_mode_resolution_is_deterministic(message, expected):
    assert resolve_account_mode(_context(message)) == expected


def test_trade_keywords_win_over_query_keywords():
    """"清仓我的持仓"里同时有查询词，必须按交易引导处理（更安全）。"""
    assert resolve_account_mode(_context("帮我清仓我的持仓")) == "trade_guidance"


def test_account_domain_is_registered_in_domain_order():
    """新增领域必须同时进入 _DOMAIN_ORDER，否则排序会 ValueError。"""
    assert BusinessDomain.ACCOUNT_PORTFOLIO in _DOMAIN_ORDER


def test_account_intent_routes_to_account_domain():
    class _Classifier:
        def classify_intents(self, message, context_summary=""):
            return {
                "intents": [{
                    "intent": "account_query", "query": message, "confidence": 0.97,
                    "evidence": message, "execution_mode": "position_query",
                }],
                "finance_related": True,
            }

    decision = classify_domains("我的持仓怎么样", classifier=_Classifier())
    assert decision.domains == [BusinessDomain.ACCOUNT_PORTFOLIO]
    assert decision.execution_mode == "domain_react"


# ── 摘要内容 ──────────────────────────────────────────────────────

def test_account_overview_summarizes_cash_and_pnl(service):
    service.deposit(CUSTOMER, 100000.0)
    service.buy(CUSTOMER, "110011", amount=38500.0)
    outcome = _run(service, "我的账户里还有多少钱")

    assert outcome.status == "success"
    assert outcome.domain == BusinessDomain.ACCOUNT_PORTFOLIO
    assert "可用资金" in outcome.summary
    assert "总资产" in outcome.summary
    assert "模拟交易" in outcome.summary
    assert outcome.structured_data["account"]["cash_balance"] == pytest.approx(61500.0, abs=0.05)


def test_position_query_lists_each_holding(service):
    service.deposit(CUSTOMER, 100000.0)
    service.buy(CUSTOMER, "110011", amount=10000.0)
    outcome = _run(service, "我的持仓怎么样")

    assert "易方达中小盘混合" in outcome.summary
    assert "浮动盈亏" in outcome.summary
    assert len(outcome.structured_data["positions"]) == 1


def test_position_query_without_holdings_says_so(service):
    outcome = _run(service, "我的持仓怎么样")
    assert outcome.status == "success"
    assert "没有持仓" in outcome.summary
    assert outcome.structured_data["positions"] == []


def test_unpriced_position_marks_partial_and_warns(service):
    from datetime import datetime

    service.deposit(CUSTOMER, 100000.0)
    service.store.positions[(CUSTOMER, "999999")] = {
        "customer_id": CUSTOMER, "product_code": "999999", "shares": 100.0,
        "cost_amount": 100.0, "avg_cost": 1.0,
        "opened_at": datetime.now(), "updated_at": datetime.now(),
    }
    outcome = _run(service, "我的持仓怎么样")
    assert outcome.status == "partial"
    assert any(item.startswith("pricing_issue:") for item in outcome.limitations)
    assert "缺少可用净值" in outcome.summary


def test_service_failure_returns_safe_text_not_exception(service):
    """服务不可用时给固定文案，不把原始异常拼进回复。"""

    class _Broken:
        def get_account(self, customer_id):
            raise RuntimeError("connection refused to db host 10.0.0.5")

    outcome = build_account_domain_graph(
        deps=AccountDomainDeps(service=_Broken())
    ).invoke({"context": _context("我的账户余额")})["domain_outcome"]

    assert outcome.status == "failed"
    assert "10.0.0.5" not in outcome.summary
    assert outcome.limitations == ["account_service_failed"]


# ── 交易引导不执行任何操作 ────────────────────────────────────────

@pytest.mark.parametrize("message", [
    "帮我买 1000 块 110011",
    "帮我卖掉我的持仓",
    "我要一键清仓",
    "帮我充值 5000 元",
])
def test_trade_intent_returns_guidance_without_executing(service, message):
    """交易意图只给引导文案，既不成交也不改余额。"""
    service.deposit(CUSTOMER, 100000.0)
    service.buy(CUSTOMER, "110011", amount=10000.0)
    before = service.get_account(CUSTOMER)
    orders_before = len(service.list_orders(CUSTOMER))

    outcome = _run(service, message)

    assert outcome.summary == TRADE_GUIDANCE
    assert outcome.structured_data["executed"] is False
    after = service.get_account(CUSTOMER)
    assert after.cash_balance == before.cash_balance
    assert after.position_count == before.position_count
    assert len(service.list_orders(CUSTOMER)) == orders_before


def test_account_domain_never_writes_to_store(service):
    """只读不变量：跑完所有模式后存储里不新增任何委托或资金流水。"""
    service.deposit(CUSTOMER, 100000.0)
    service.buy(CUSTOMER, "110011", amount=10000.0)
    orders_before = len(service.store.orders)
    txns_before = len(service.store.transactions)

    for message in ("我的账户", "我的持仓", "帮我清仓", "帮我充值"):
        _run(service, message)

    assert len(service.store.orders) == orders_before
    assert len(service.store.transactions) == txns_before


# ── 未注册模式安全失败 ────────────────────────────────────────────

def test_unregistered_mode_fails_without_falling_back(service):
    """白名单之外的模式必须安全失败，不得静默降级到其它领域工具。

    这里给一个只注册 ``trade_guidance`` 的白名单，然后问一个会解析成
    ``account_overview`` 的问题：应得到 ``unsupported_mode`` 而非借用交易引导，
    也不应真的去查账户。
    """
    from finance_agent.orchestrator.domains.account import default_account_operations

    only_guidance = [
        op for op in default_account_operations(AccountDomainDeps(service=service))
        if op.name == "trade_guidance"
    ]
    graph = build_account_domain_graph(
        operations=only_guidance, deps=AccountDomainDeps(service=service),
    )
    failed = graph.invoke({"context": _context("我的账户余额")})["domain_outcome"]
    assert failed.status == "failed"
    assert failed.limitations == ["unsupported_mode:account_overview"]
    assert failed.summary == ""
