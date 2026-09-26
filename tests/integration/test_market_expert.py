"""市场洞察专家（LangGraph ReAct）测试：采集 JSON 写入 market_insight。"""

from __future__ import annotations

from finance_agent.orchestration.contracts import (
    BusinessDomain,
    DomainTaskContext,
    PlanTask,
)
from finance_agent.orchestration.experts import build_expert
from finance_agent.domains.market.expert import market_tools
from finance_agent.domains.market.expert import tools as tools_market
from finance_agent.orchestration.experts.base import ExpertSink, default_assemble
from finance_agent.domains.market.expert.tools import (
    MODE_COLLECTORS,
    unavailable_for,
)

from tests.conftest import final_message, make_fake_tool_model, tool_call


def _context(goal: str = "今天大盘怎么样",
             domain: BusinessDomain = BusinessDomain.MARKET_INSIGHT):
    return DomainTaskContext(
        task=PlanTask(
            task_id="t-1", domain=domain,
            goal=goal, instruction=goal, expected_output="domain_outcome",
        ),
        thread_id="v1:CUST1:conv-1",
        customer_id="CUST1",
        conversation_id="conv-1",
        user_message=goal,
    )


def _run_mode(mode: str, monkeypatch, *, collector=None):
    if collector is not None:
        monkeypatch.setitem(MODE_COLLECTORS, mode, collector)
    sink = ExpertSink(domain=BusinessDomain.MARKET_INSIGHT, customer_id="CUST1")
    result = tools_market._run_mode(sink, mode)
    assembly = default_assemble(sink, "")
    return result, sink, assembly


_OVERVIEW_FULL = {
    "as_of": "2026-09-11",
    "indices": [
        {"symbol": "sh000001", "name": "上证指数", "close": 3888.11, "pct_chg": -1.18},
        {"symbol": "sh000300", "name": "沪深300", "close": 4510.16, "pct_chg": -0.5},
    ],
    "breadth": {"advancing": 604, "declining": 4567, "limit_up": 40, "limit_down": 21},
    "limitations": [],
    "note": "",
}


def test_overview_mode_records_real_numbers(monkeypatch):
    _, sink, assembly = _run_mode(
        "market_overview", monkeypatch, collector=lambda: dict(_OVERVIEW_FULL),
    )

    assert assembly.status == "success"
    insight = assembly.structured_data["market_insight"]
    assert insight["mode"] == "market_overview"
    assert insight["indices"][0]["close"] == 3888.11
    assert insight["breadth"]["advancing"] == 604
    assert "stock_analysis" not in assembly.structured_data
    assert "analysis_results" not in assembly.structured_data


def test_partial_failures_are_disclosed_not_faked(monkeypatch):
    _, sink, assembly = _run_mode("market_overview", monkeypatch, collector=lambda: {
        "as_of": "2026-09-11",
        "indices": [{"symbol": "sh000001", "name": "上证指数", "close": 3888.11,
                     "pct_chg": -1.18}],
        "breadth": {},
        "limitations": ["market_breadth"],
        "note": "",
    })

    assert assembly.status == "partial"
    assert "market_breadth" in assembly.limitations
    assert assembly.structured_data["market_insight"]["indices"][0]["close"] == 3888.11
    assert not assembly.structured_data["market_insight"].get("breadth")


def test_all_data_missing_degrades_honestly(monkeypatch):
    result, sink, assembly = _run_mode("market_overview", monkeypatch, collector=lambda: {
        "as_of": "", "indices": [], "breadth": {}, "limitations": ["market_breadth"], "note": "",
    })

    assert assembly.status == "partial"
    assert "no_data" in assembly.limitations
    assert "暂不可用" in result["error"]
    assert result["error"] == unavailable_for("market_overview")
    assert "market_insight" not in assembly.structured_data


def test_sentiment_mode_records_breadth(monkeypatch):
    payload = {
        "as_of": "2026-09-11",
        "breadth": {"advancing": 604, "declining": 4567, "limit_up": 40,
                    "limit_down": 21, "flat": 36, "suspended": 12, "activity": 11.57},
        "benchmark": {"name": "上证指数", "close": 3888.11, "pct_chg": -1.18},
        "limitations": [],
        "note": "",
    }
    _, _, assembly = _run_mode(
        "market_sentiment", monkeypatch, collector=lambda: dict(payload),
    )

    insight = assembly.structured_data["market_insight"]
    assert insight["mode"] == "market_sentiment"
    assert insight["breadth"]["activity"] == 11.57
    assert insight["benchmark"]["close"] == 3888.11


def test_capital_flow_mode_records_margin_and_holdings(monkeypatch):
    payload = {
        "as_of": "2026-09-10",
        "margin": {
            "as_of": "2026-09-10", "financing_balance_yi": 26171.760561,
            "securities_lending_balance_yi": 291.914989,
            "total_balance_yi": 26463.67555, "financing_buy_yi": 1363.108363,
        },
        "northbound_holdings": {"as_of": "2026-06-30",
                                "holdings_value_yuan": 3102375003773},
        "limitations": [],
        "note": "融资融券为两市合计、交易所日频披露；北向持股市值季度披露。",
    }
    _, _, assembly = _run_mode(
        "capital_flow", monkeypatch, collector=lambda: dict(payload),
    )

    insight = assembly.structured_data["market_insight"]
    assert insight["mode"] == "capital_flow"
    assert insight["margin"]["financing_balance_yi"] == 26171.760561
    assert insight["northbound_holdings"]["holdings_value_yuan"] == 3102375003773


def test_capital_flow_lists_missing_source_instead_of_faking(monkeypatch):
    _, _, assembly = _run_mode("capital_flow", monkeypatch, collector=lambda: {
        "as_of": "2026-09-10",
        "margin": {"as_of": "2026-09-10", "financing_balance_yi": 26171.760561},
        "northbound_holdings": {},
        "limitations": ["northbound_holdings"],
        "note": "",
    })

    assert assembly.status == "partial"
    assert "northbound_holdings" in assembly.limitations
    assert "northbound_holdings" in assembly.structured_data["market_insight"]["limitations"]


def test_capital_flow_degrades_when_all_missing(monkeypatch):
    result, _, assembly = _run_mode("capital_flow", monkeypatch, collector=lambda: {
        "as_of": "", "margin": {}, "northbound_holdings": {},
        "limitations": ["margin_summary", "northbound_holdings"], "note": "",
    })

    assert assembly.status == "partial"
    assert "no_data" in assembly.limitations
    assert "暂不可用" in result["error"] or "暂无" in result["error"]


def test_unavailable_message_is_mode_specific(monkeypatch):
    result, _, _ = _run_mode("capital_flow", monkeypatch, collector=lambda: {
        "as_of": "", "margin": {}, "northbound_holdings": {},
        "limitations": ["margin_summary", "northbound_holdings"], "note": "",
    })

    assert "融资融券" in result["error"]
    assert "市场宽度" not in result["error"]


def test_market_mode_rejects_unknown_mode(monkeypatch):
    result, sink, assembly = _run_mode("fx_flow", monkeypatch)

    assert assembly.status == "partial"
    assert "unsupported_mode:fx_flow" in assembly.limitations
    assert "暂不支持" in result["error"]


def test_mode_collectors_binds_callables_and_unknown_is_absent():
    for mode, collector in MODE_COLLECTORS.items():
        assert callable(collector)
    assert MODE_COLLECTORS.get("fx_flow") is None


_POLICY_PAYLOAD = {
    "as_of": "2026-09-13 08:00:00",
    "events": [
        {"datetime": "2026-09-13 08:00:00", "title": "央行开展逆回购操作", "category": "货币政策"},
        {"datetime": "2026-09-12 19:00:00", "title": "证监会发布减持新规", "category": "资本市场监管"},
    ],
    "categories_summary": {"货币政策": 1, "资本市场监管": 1},
    "window_days": 3,
    "limitations": [],
    "note": "政策事件按关键词确定性筛选（近 3 天财经快讯），非全量新闻。",
}


def test_policy_impact_records_events_without_interpretation(monkeypatch):
    _, _, assembly = _run_mode(
        "policy_impact", monkeypatch, collector=lambda: dict(_POLICY_PAYLOAD),
    )

    assert assembly.status == "success"
    insight = assembly.structured_data["market_insight"]
    assert insight["mode"] == "policy_impact"
    titles = [item["title"] for item in insight["events"]]
    assert "央行开展逆回购操作" in titles
    assert insight["categories_summary"]["货币政策"] == 1
    assert "stock_analysis" not in assembly.structured_data


def test_policy_impact_reports_empty_state_honestly(monkeypatch):
    _, _, assembly = _run_mode("policy_impact", monkeypatch, collector=lambda: {
        "as_of": "", "events": [], "categories_summary": {},
        "window_days": 3, "limitations": [], "note": "",
    })

    assert assembly.status == "success"
    assert assembly.structured_data["market_insight"]["events"] == []


def test_policy_impact_degrades_when_news_source_unavailable(monkeypatch):
    result, _, assembly = _run_mode("policy_impact", monkeypatch, collector=lambda: {
        "as_of": "", "events": [], "categories_summary": {},
        "window_days": 3, "limitations": ["policy_news"], "note": "",
    })

    assert assembly.status == "partial"
    assert "policy_news" in assembly.limitations
    assert "财经快讯" in result["error"]


def test_market_expert_tool_whitelist():
    names = [tool.name for tool in market_tools()]
    assert names == [
        "get_market_overview", "get_market_sentiment",
        "get_capital_flow", "get_policy_impact",
    ]
    foreign = {
        "query_product", "list_products",
        "resolve_stock_names", "compute_technical",
        "get_positions", "review_allocation",
    }
    assert set(names).isdisjoint(foreign)


def test_market_expert_refuses_foreign_task():
    graph = build_expert(BusinessDomain.MARKET_INSIGHT, model=make_fake_tool_model([]))
    outcome = graph.invoke(
        {"context": _context(domain=BusinessDomain.STOCK_RESEARCH, goal="分析600519")}
    )["domain_outcome"]

    assert outcome.status == "failed"
    assert outcome.limitations == ["domain_mismatch"]


def test_market_expert_combines_multiple_modes(monkeypatch):
    monkeypatch.setitem(MODE_COLLECTORS, "market_overview", lambda: {
        "as_of": "2026-09-11",
        "indices": [{"name": "上证指数", "close": 3888.11, "pct_chg": -1.18}],
        "breadth": {}, "limitations": [], "note": "",
    })
    monkeypatch.setitem(MODE_COLLECTORS, "capital_flow", lambda: {
        "as_of": "2026-09-10",
        "margin": {"as_of": "2026-09-10", "financing_balance_yi": 26171.76},
        "northbound_holdings": {}, "limitations": [], "note": "",
    })
    model = make_fake_tool_model([
        tool_call("get_market_overview"),
        tool_call("get_capital_flow", call_id="c2"),
        final_message("大盘与资金面综合如上。"),
    ])
    graph = build_expert(BusinessDomain.MARKET_INSIGHT, model=model)
    outcome = graph.invoke(
        {"context": _context(goal="大盘和资金面怎么样")}
    )["domain_outcome"]

    assert outcome.status == "success"
    payload = outcome.structured_data["market_insight"]
    assert payload["mode"] == "multi"
    assert {item["mode"] for item in payload["items"]} == {"market_overview", "capital_flow"}
    assert payload["items"][0]["indices"][0]["close"] == 3888.11
    assert payload["items"][1]["margin"]["financing_balance_yi"] == 26171.76
    assert outcome.summary == "大盘与资金面综合如上。"


def test_market_expert_model_failure_is_safe():
    class _BoomModel:
        def bind_tools(self, tools, **kwargs):
            return self

        def invoke(self, *args, **kwargs):
            raise RuntimeError("market model down host 10.9.9.9")

    graph = build_expert(BusinessDomain.MARKET_INSIGHT, model=_BoomModel())
    outcome = graph.invoke({"context": _context()})["domain_outcome"]

    assert outcome.status == "failed"
    assert outcome.limitations == ["expert_unavailable"]
    assert outcome.summary == "市场数据暂时无法生成，请稍后重试。"
    assert "10.9.9.9" not in outcome.summary
