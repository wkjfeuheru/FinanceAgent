"""账户/持仓专家（LangGraph ReAct）测试：只读不变量与测算 JSON。

``review_allocation`` 把测算结果写入 ``allocation_review``（前端卡片仍读该键）；
用户可见正文是模型分析，不再拼接五段式中文模板。
"""

from __future__ import annotations

from datetime import datetime

import pytest

from finance_agent.orchestration.contracts import (
    BusinessDomain,
    DomainTaskContext,
    PlanTask,
)
from finance_agent.orchestration.experts import build_expert
from finance_agent.domains.portfolio.expert import tools as tools_account
from finance_agent.domains.portfolio.service import PortfolioDeps, PortfolioService

from tests.conftest import final_message, make_fake_tool_model, tool_call
from tests.integration.test_portfolio_service import (  # noqa: E402 - 复用服务层内存假件
    PRODUCTS,
    _FakeLibrary,
    _FakeNavSource,
    _FakeStore,
)

CUSTOMER = "CUST000001"


def _context(message: str, domain=BusinessDomain.ACCOUNT_PORTFOLIO, profile: dict | None = None):
    return DomainTaskContext(
        task=PlanTask(
            task_id="t-1", domain=domain,
            goal=message, instruction=message, expected_output="domain_outcome",
        ),
        thread_id=f"v1:{CUSTOMER}:conv",
        customer_id=CUSTOMER,
        conversation_id="conv",
        user_message=message,
        user_profile=profile or {},
    )


@pytest.fixture()
def service():
    return PortfolioService(PortfolioDeps(
        store=_FakeStore(),
        library=_FakeLibrary(PRODUCTS),
        nav_source=_FakeNavSource({"110011": 3.85, "003003": 1.0}),
    ))


def _run(monkeypatch, service, message: str, profile: dict | None = None):
    """跑一次账户专家：模型先调 review_allocation，再给收尾分析。"""
    monkeypatch.setattr(tools_account, "_service", lambda: service)
    model = make_fake_tool_model([
        tool_call("review_allocation"),
        final_message("（模型转述，不应覆盖权威文案）"),
    ])
    graph = build_expert(BusinessDomain.ACCOUNT_PORTFOLIO, model=model)
    return graph.invoke({"context": _context(message, profile=profile)})["domain_outcome"]


# ── 配置诊断（review_allocation）──────────────────────────────────

def test_allocation_review_reports_concentration_and_metrics(monkeypatch, service):
    service.deposit(CUSTOMER, 100000.0)
    service.buy(CUSTOMER, "110011", amount=60000.0)
    service.buy(CUSTOMER, "003003", amount=40000.0)
    outcome = _run(monkeypatch, service, "我的持仓怎么优化", {"risk_preference": "稳健"})

    assert outcome.status == "success"
    review = outcome.structured_data["allocation_review"]
    assert review["profile_used"] is True
    assert review["risk_preference"] == "R2"
    assert review["concentration"]["effective_n"] is not None
    assert review["concentration"]["top1_weight"] is not None


def test_allocation_review_gives_per_holding_suggestions(monkeypatch, service):
    """回答必须是可读散文且含持仓级方向建议与优化前后指标对比。"""
    service.deposit(CUSTOMER, 100000.0)
    service.buy(CUSTOMER, "110011", amount=60000.0)
    service.buy(CUSTOMER, "003003", amount=40000.0)
    outcome = _run(monkeypatch, service, "我的持仓怎么优化", {"risk_preference": "稳健"})

    opt = outcome.structured_data["allocation_review"]["optimization"]
    assert opt["basis"] == "risk_band"
    assert opt["coverage"]["covered"] == 2 and opt["coverage"]["total"] == 2
    assert {row["product_code"] for row in opt["targets"]} == {"110011", "003003"}
    assert any(row.get("direction") in ("提高", "降低") for row in opt["targets"])
    assert "volatility" in (opt.get("before") or {}) or "volatility" in (opt.get("after") or {})


def test_allocation_review_without_profile_still_suggests(monkeypatch, service):
    """未设风险偏好：给出补充引导，同时仍基于逆波动率给出具体建议。"""
    service.deposit(CUSTOMER, 100000.0)
    service.buy(CUSTOMER, "110011", amount=60000.0)
    service.buy(CUSTOMER, "003003", amount=40000.0)
    outcome = _run(monkeypatch, service, "资产配置合理吗")

    opt = outcome.structured_data["allocation_review"]["optimization"]
    assert opt["basis"] == "inverse_volatility"
    assert outcome.structured_data["allocation_review"]["profile_used"] is False


def test_allocation_review_never_reports_100pct_target_for_single_covered_holding(
    monkeypatch, service,
):
    """回归：两只持仓同档位、其中一只缺波动率时，目标不得退化为 100%。

    此前优化集合只含"有波动率"的持仓，单只归一后目标=100%、方向恒为"维持"，
    并掩盖真实的档位失衡（截图现象）。
    """
    service.deposit(CUSTOMER, 100000.0)
    service.buy(CUSTOMER, "110011", amount=50000.0)
    service.buy(CUSTOMER, "003003", amount=50000.0)
    # 让其中一只缺波动率，另一只保留。
    original = service.position_risk_facts

    def _facts(customer_id):
        facts = dict(original(customer_id))
        facts.pop("003003", None)
        return facts

    service.position_risk_facts = _facts  # type: ignore[method-assign]
    outcome = _run(monkeypatch, service, "我的持仓配置怎么优化", {"risk_preference": "稳健"})

    opt = outcome.structured_data["allocation_review"]["optimization"]
    targets = {row["product_code"]: row for row in opt["targets"]}
    assert set(targets) == {"110011", "003003"}, "缺波动率的持仓仍须在优化集合内"
    assert all(row["target"] < 1.0 for row in targets.values()), "单只不得占满 100%"
    # 档位层必须给出偏离与方向（全部同档位时，这是唯一可操作的建议）。
    statuses = {gap["tier"]: gap["status"] for gap in opt["tier_gaps"]}
    assert "above" in statuses.values() or "absent" in statuses.values()


def test_allocation_review_without_profile_advises_on_concentration(monkeypatch):
    """无画像 + 全部持仓同档位：仍须给出结构性建议，不得只说"无法给区间"。

    截图场景：两只持仓都是高风险、其中一只缺波动率、且未设偏好。此时既无参考
    区间、持仓级目标又退化，唯一可操作的建议是"引入中低风险品种分散"。
    """
    monkeypatch.setitem(PRODUCTS, "161725", {
        "name": "招商中证白酒指数A", "nav": 1.05, "subscription_fee": 1.0,
        "redemption_fee": "0.5%", "risk_level": "R4 中高风险",
        "volatility": 0.238, "return_1y": 0.033, "max_drawdown": 0.412,
    })
    monkeypatch.setitem(PRODUCTS, "012345", {
        "name": "科技创新混合C", "nav": 1.0856, "subscription_fee": 1.0,
        "redemption_fee": "0.5%", "risk_level": "R4 中高风险",
        # 缺波动率：验证"缺数据不得导致目标退化为 100%"。
        "volatility": None, "return_1y": 0.285, "max_drawdown": 0.018,
    })
    svc = PortfolioService(PortfolioDeps(
        store=_FakeStore(),
        library=_FakeLibrary(PRODUCTS),
        nav_source=_FakeNavSource({"161725": 1.05, "012345": 1.0856}),
    ))
    svc.deposit(CUSTOMER, 100000.0)
    svc.buy(CUSTOMER, "161725", amount=50000.0)
    svc.buy(CUSTOMER, "012345", amount=50000.0)

    outcome = _run(monkeypatch, svc, "我的持仓配置怎么优化，最近亏了很多")

    opt = outcome.structured_data["allocation_review"]["optimization"]
    assert opt["coverage"] == {"covered": 1, "total": 2, "uncovered": ["012345"]}
    # 目标不得退化为单只 100%。
    assert all(row["target"] < 1.0 for row in opt["targets"])
    assert opt["coverage"]["uncovered"] == ["012345"]


def test_allocation_review_without_profile_skips_band_comparison(monkeypatch, service):
    service.deposit(CUSTOMER, 100000.0)
    service.buy(CUSTOMER, "110011", amount=10000.0)
    outcome = _run(monkeypatch, service, "资产配置合理吗")

    review = outcome.structured_data["allocation_review"]
    assert review["profile_used"] is False
    assert review["deviations"] == []


def test_allocation_review_without_holdings_guides_to_product_page(monkeypatch, service):
    outcome = _run(monkeypatch, service, "我的持仓怎么优化")
    assert outcome.status == "success"
    assert outcome.structured_data["allocation_review"] == {}


def test_allocation_review_unpriced_holdings_mark_partial(monkeypatch, service):
    """无定价持仓不计入占比：partial + limitations 提示。"""
    service.deposit(CUSTOMER, 100000.0)
    service.store.positions[(CUSTOMER, "999999")] = {
        "customer_id": CUSTOMER, "product_code": "999999", "shares": 100.0,
        "cost_amount": 100.0, "avg_cost": 1.0,
        "opened_at": datetime.now(), "updated_at": datetime.now(),
    }
    outcome = _run(monkeypatch, service, "我的持仓怎么优化")
    assert outcome.status == "partial"
    assert outcome.limitations == ["no_priced_holdings"]
    # 未定价代码登记在 review 的 unpriced 列表里，供前端展示。
    assert outcome.structured_data["allocation_review"]["unpriced"] == ["999999"]


def test_allocation_review_never_emits_buy_sell_instructions(monkeypatch, service):
    """措辞必须不含敏感词：合规出口会对命中词删词，改写失败即拦截。"""
    from finance_agent.safety import check_sensitive_words

    service.deposit(CUSTOMER, 100000.0)
    service.buy(CUSTOMER, "110011", amount=60000.0)
    service.buy(CUSTOMER, "003003", amount=40000.0)
    outcome = _run(monkeypatch, service, "我的持仓怎么优化", {"risk_preference": "稳健"})

    assert check_sensitive_words(outcome.summary) == []


def test_account_expert_never_writes_to_store(monkeypatch, service):
    """只读不变量：跑完配置诊断后存储里不新增任何委托或资金流水。"""
    service.deposit(CUSTOMER, 100000.0)
    service.buy(CUSTOMER, "110011", amount=10000.0)
    orders_before = len(service.store.orders)
    txns_before = len(service.store.transactions)

    for message in ("我的持仓怎么优化", "资产配置合理吗"):
        _run(monkeypatch, service, message, {"risk_preference": "平衡"})

    assert len(service.store.orders) == orders_before
    assert len(service.store.transactions) == txns_before


def test_service_failure_returns_safe_text_not_exception(monkeypatch):
    """服务不可用时给固定文案，不把原始异常拼进回复。"""

    class _Broken:
        def get_account(self, customer_id):
            raise RuntimeError("connection refused to db host 10.0.0.5")

    monkeypatch.setattr(tools_account, "_service", lambda: _Broken())
    model = make_fake_tool_model([
        tool_call("review_allocation"),
        final_message("账户数据暂不可用。"),
    ])
    graph = build_expert(BusinessDomain.ACCOUNT_PORTFOLIO, model=model)
    outcome = graph.invoke(
        {"context": _context("我的持仓怎么优化")}
    )["domain_outcome"]

    assert outcome.status == "failed"
    assert outcome.limitations == ["account_service_failed"]
    assert "10.0.0.5" not in outcome.summary
    assert tools_account.ACCOUNT_UNAVAILABLE == "账户数据暂不可用，请稍后在「账户」页面查看，或稍后重试。"


def test_review_allocation_tool_reports_fixed_text_on_service_failure(monkeypatch):
    """工具层直接验证：失败时回给模型的是固定安全文案（不含异常细节）。"""
    from finance_agent.orchestration.experts.base import ExpertSink, SINK_KEY

    class _Broken:
        def get_account(self, customer_id):
            raise RuntimeError("connection refused to db host 10.0.0.5")

    monkeypatch.setattr(tools_account, "_service", lambda: _Broken())
    sink = ExpertSink(domain=BusinessDomain.ACCOUNT_PORTFOLIO, customer_id=CUSTOMER)
    raw = tools_account.review_allocation.invoke(
        {}, config={"configurable": {SINK_KEY: sink}},
    )

    assert tools_account.ACCOUNT_UNAVAILABLE in raw
    assert "10.0.0.5" not in raw
    assert sink.failed is True
    assert "account_service_failed" in sink.limitations


# ── 专家级通用不变量 ──────────────────────────────────────────────

def test_account_expert_refuses_foreign_task(monkeypatch):
    """账户专家拿到股票领域任务必须安全失败，且不调用任何工具/模型。"""
    from finance_agent.orchestration.contracts import BusinessDomain as BD

    # 空消息序列：一旦模型被调用就会 StopIteration，从而暴露"越权执行"。
    graph = build_expert(BD.ACCOUNT_PORTFOLIO, model=make_fake_tool_model([]))
    context = _context("分析600519", domain=BD.STOCK_RESEARCH)
    outcome = graph.invoke({"context": context})["domain_outcome"]

    assert outcome.status == "failed"
    assert outcome.limitations == ["domain_mismatch"]


def test_account_expert_rejects_unknown_request_user_input_field(monkeypatch):
    """账户域没有可追问字段：模型自造字段不得生成弹窗表单。"""
    model = make_fake_tool_model([
        tool_call("request_user_input", {"fields": ["stock_target"]}),
        final_message("好的。"),
    ])
    graph = build_expert(BusinessDomain.ACCOUNT_PORTFOLIO, model=model)
    outcome = graph.invoke(
        {"context": _context("我的持仓怎么优化")}
    )["domain_outcome"]

    assert outcome.status != "needs_input"
    assert "pending_input" not in outcome.structured_data
