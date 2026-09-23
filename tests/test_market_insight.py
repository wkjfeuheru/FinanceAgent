"""市场洞察领域：边界、四模式实数渲染与降级。

``market_insight`` 只回答市场级问题，绝不输出个股结论、推荐或配置。
取数经 ``tools.marketdata`` 注入，测试不联网。
"""

from __future__ import annotations

import pytest

import finance_agent.orchestrator.domains.market as market_module
from finance_agent.orchestrator.contracts import BusinessDomain, DomainTaskContext, PlanTask
from finance_agent.orchestrator.domains.market import (
    PolicyImpactInterpreter,
    build_market_domain_graph,
    run_market_mode,
)
from finance_agent.orchestrator.graphs.supervisor_graph import SupervisorDependencies, build_supervisor_graph


def _render(mode: str, *, interpreter=None):
    """执行单个市场模式，返回统一结果。"""
    return run_market_mode(mode, interpreter=interpreter or _NoopInterpreter())


class _NoopInterpreter:
    def interpret(self, events, as_of, window_days):
        raise AssertionError("policy interpreter 不应在非 policy 模式被调用")


def _context(goal: str) -> DomainTaskContext:
    return DomainTaskContext(
        task=PlanTask(
            task_id="single:run-1:market_insight",
            domain=BusinessDomain.MARKET_INSIGHT,
            goal=goal,
            instruction=goal,
            expected_output="domain_outcome",
        ),
        thread_id="v1:CUST1:conv-1",
        customer_id="CUST1",
        conversation_id="conv-1",
        user_message=goal,
    )


@pytest.fixture
def overview_data(monkeypatch):
    payload = {
        "as_of": "2026-09-11",
        "indices": [
            {"symbol": "sh000001", "name": "上证指数", "as_of": "2026-09-11",
             "close": 3888.11, "pct_chg": -1.18, "recent_closes": [3900.0, 3888.11]},
            {"symbol": "sh000300", "name": "沪深300", "as_of": "2026-09-11",
             "close": 4510.16, "pct_chg": -0.5, "recent_closes": [4530.0, 4510.16]},
        ],
        "breadth": {"advancing": 604, "declining": 4567, "limit_up": 40,
                    "limit_down": 21, "activity": 11.57, "as_of": "2026-09-11"},
        "limitations": [],
        "note": "",
    }
    monkeypatch.setitem(market_module.MODE_COLLECTORS, "market_overview", lambda: payload)
    return payload


def test_overview_mode_renders_real_numbers(overview_data):
    result = _render("market_overview")

    assert result.status == "success"
    assert "上证指数" in result.summary
    assert "3,888.11" in result.summary
    assert "-1.18%" in result.summary
    assert "上涨 604 家" in result.summary
    assert result.structured_data["market_insight"]["mode"] == "market_overview"
    # 硬边界：不得产出任何个股结论字段。
    assert "stock_analysis" not in result.structured_data
    assert "analysis_results" not in result.structured_data


def test_sentiment_mode_renders_breadth(monkeypatch):
    monkeypatch.setitem(market_module.MODE_COLLECTORS, "market_sentiment", lambda: {
        "as_of": "2026-09-11",
        "breadth": {"advancing": 604, "declining": 4567, "limit_up": 40,
                    "limit_down": 21, "flat": 36, "suspended": 12, "activity": 11.57},
        "benchmark": {"name": "上证指数", "close": 3888.11, "pct_chg": -1.18},
        "limitations": [],
        "note": "",
    })

    result = _render("market_sentiment")

    assert "市场情绪" in result.summary
    assert "偏弱" in result.summary          # 下跌多于上涨
    assert "11.57%" in result.summary
    assert result.structured_data["market_insight"]["mode"] == "market_sentiment"


def test_capital_flow_mode_renders_margin_and_holdings(monkeypatch):
    """capital_flow 以融资融券（日频主指标）+ 北向持股市值（季度参考）呈现。"""
    monkeypatch.setitem(market_module.MODE_COLLECTORS, "capital_flow", lambda: {
        "as_of": "2026-09-10",
        "margin": {
            "as_of": "2026-09-10", "financing_balance_yi": 26171.760561,
            "securities_lending_balance_yi": 291.914989,
            "total_balance_yi": 26463.67555, "financing_buy_yi": 1363.108363,
        },
        "northbound_holdings": {"as_of": "2026-06-30",
                                "holdings_value_yuan": 3102375003773},
        "limitations": [],
        "note": "融资融券为两市合计、交易所日频披露；北向持股市值为季度披露，非实时。",
    })

    result = _render("capital_flow")

    assert "融资融券（两市合计，2026-09-10）" in result.summary
    assert "26,171.76 亿元" in result.summary        # 融资余额
    assert "26,463.68 亿元" in result.summary        # 两融余额
    assert "北向持股市值（2026-06-30，季度披露）" in result.summary
    assert "31,023.75 亿元" in result.summary
    assert result.structured_data["market_insight"]["mode"] == "capital_flow"


def test_capital_flow_lists_missing_source_instead_of_faking(monkeypatch):
    monkeypatch.setitem(market_module.MODE_COLLECTORS, "capital_flow", lambda: {
        "as_of": "2026-09-10",
        "margin": {"as_of": "2026-09-10", "financing_balance_yi": 26171.760561},
        "northbound_holdings": {},
        "limitations": ["northbound_holdings"],
        "note": "融资融券为两市合计、交易所日频披露；北向持股市值为季度披露，非实时。",
    })

    result = _render("capital_flow")

    assert result.status == "partial"
    assert "northbound_holdings" in result.summary


def test_capital_flow_degrades_when_all_missing(monkeypatch):
    monkeypatch.setitem(market_module.MODE_COLLECTORS, "capital_flow", lambda: {
        "as_of": "", "margin": {}, "northbound_holdings": {},
        "limitations": ["margin_summary", "northbound_holdings"], "note": "",
    })

    result = _render("capital_flow")

    assert result.status == "partial"
    assert "暂无" in result.summary or "暂不可用" in result.summary


def test_partial_failures_are_disclosed_not_faked(monkeypatch):
    monkeypatch.setitem(market_module.MODE_COLLECTORS, "market_overview", lambda: {
        "as_of": "2026-09-11",
        "indices": [{"symbol": "sh000001", "name": "上证指数", "close": 3888.11,
                     "pct_chg": -1.18}],
        "breadth": {},
        "limitations": ["market_breadth"],
        "note": "",
    })

    result = _render("market_overview")

    assert result.status == "partial"
    assert "限制与提示" in result.summary
    assert "market_breadth" in result.summary


def test_all_data_missing_degrades_honestly(monkeypatch):
    monkeypatch.setitem(market_module.MODE_COLLECTORS, "market_overview", lambda: {
        "as_of": "", "indices": [], "breadth": {}, "limitations": ["market_breadth"], "note": "",
    })

    result = _render("market_overview")

    assert result.status == "partial"
    assert "暂不可用" in result.summary


def test_market_domain_rejects_unknown_mode():
    result = run_market_mode("fx_flow", interpreter=_NoopInterpreter())

    assert result.status == "partial"
    assert "暂不支持" in result.summary


def test_market_overview_renders_turnover_and_range(monkeypatch):
    """大盘概览盘活已有数据：成交额与近 5/20 日区间涨跌。"""
    monkeypatch.setitem(market_module.MODE_COLLECTORS, "market_overview", lambda: {
        "as_of": "2026-09-11",
        "indices": [{
            "symbol": "sh000001", "name": "上证指数", "close": 3888.11, "pct_chg": -1.18,
            "amount": 512300000000.0, "pct_5d": -2.3, "pct_20d": 1.75,
        }],
        "breadth": {}, "limitations": [], "note": "指数为最近交易日收盘。",
    })

    result = _render("market_overview")

    assert "成交额 5,123.00 亿元" in result.summary
    assert "近5日 -2.30%" in result.summary
    assert "近20日 +1.75%" in result.summary
    # note 现在三个模式统一渲染。
    assert "数据说明：指数为最近交易日收盘。" in result.summary


def test_capital_flow_renders_day_over_day_change(monkeypatch):
    """资金面盘活已有数据：融资余额日环比。"""
    monkeypatch.setitem(market_module.MODE_COLLECTORS, "capital_flow", lambda: {
        "as_of": "2026-09-10",
        "margin": {
            "as_of": "2026-09-10", "financing_balance_yi": 26171.76,
            "securities_lending_balance_yi": 291.91, "total_balance_yi": 26463.67,
            "financing_buy_yi": 1363.11,
            "financing_balance_prev_yi": 26100.00, "financing_balance_chg_yi": 71.76,
        },
        "northbound_holdings": {},
        "limitations": [], "note": "",
    })

    result = _render("capital_flow")

    assert "融资余额较上日 +71.76 亿元" in result.summary


def test_unavailable_message_is_mode_specific(monkeypatch):
    """整体降级文案按模式区分，资金面不得误报“指数与宽度”。"""
    monkeypatch.setitem(market_module.MODE_COLLECTORS, "capital_flow", lambda: {
        "as_of": "", "margin": {}, "northbound_holdings": {},
        "limitations": ["margin_summary", "northbound_holdings"], "note": "",
    })

    result = _render("capital_flow")

    assert "融资融券" in result.summary
    assert "市场宽度" not in result.summary


class _FakeInterpreter:
    """政策解读测试替身：按需返回文本或抛异常。"""

    def __init__(self, text=None, error=None):
        self._text = text
        self._error = error

    def interpret(self, events, as_of, window_days):
        if self._error is not None:
            raise self._error
        return self._text


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


def test_policy_impact_renders_events_and_interpretation(monkeypatch):
    """政策事件模式：确定性清单 + LLM 定性解读。"""
    monkeypatch.setitem(market_module.MODE_COLLECTORS, "policy_impact", lambda: dict(_POLICY_PAYLOAD))
    interpreter = _FakeInterpreter(text="流动性边际宽松，利好市场风险偏好。")

    result = run_market_mode("policy_impact", interpreter=interpreter)

    assert result.status == "success"
    assert "央行开展逆回购操作" in result.summary
    assert "[货币政策]" in result.summary
    assert "影响解读：" in result.summary
    assert "流动性边际宽松" in result.summary
    assert result.structured_data["market_insight"]["mode"] == "policy_impact"
    # 硬边界不变。
    assert "stock_analysis" not in result.structured_data


def test_policy_impact_falls_back_to_plain_list_on_llm_failure(monkeypatch):
    """LLM 解读失败时回退纯事件清单并标注，不伪造解读。"""
    monkeypatch.setitem(market_module.MODE_COLLECTORS, "policy_impact", lambda: dict(_POLICY_PAYLOAD))
    interpreter = _FakeInterpreter(error=RuntimeError("llm down"))

    result = run_market_mode("policy_impact", interpreter=interpreter)

    assert "央行开展逆回购操作" in result.summary      # 清单仍在
    assert "影响解读暂不可用" in result.summary
    assert result.status == "partial"                  # 记入限制
    assert "policy_interpretation" in result.summary


def test_policy_impact_reports_empty_state_honestly(monkeypatch):
    """取数成功但无政策类事件时，诚实返回空态而非硬凑。"""
    monkeypatch.setitem(market_module.MODE_COLLECTORS, "policy_impact", lambda: {
        "as_of": "", "events": [], "categories_summary": {},
        "window_days": 3, "limitations": [], "note": "",
    })

    result = run_market_mode("policy_impact", interpreter=_NoopInterpreter())

    assert result.status == "success"
    assert "未筛选出政策类事件" in result.summary


def test_policy_impact_degrades_when_news_source_unavailable(monkeypatch):
    monkeypatch.setitem(market_module.MODE_COLLECTORS, "policy_impact", lambda: {
        "as_of": "", "events": [], "categories_summary": {},
        "window_days": 3, "limitations": ["policy_news"], "note": "",
    })

    result = run_market_mode("policy_impact", interpreter=_NoopInterpreter())

    assert result.status == "partial"
    assert "财经快讯" in result.summary


def test_policy_interpretation_rejects_sensitive_output():
    """解读命中敏感词时抛异常（由上层回退纯清单）。"""
    class _FakeChain:
        def invoke(self, _):
            return "这只股票必涨，建议买入。"

    interpreter = PolicyImpactInterpreter()
    interpreter._chain = _FakeChain()

    with pytest.raises(ValueError):
        interpreter.interpret([{"title": "某政策"}], "2026-09-13", 3)


def _market_classifier(intent: str):
    class _C:
        def classify_intents(self, message, context_summary=""):
            return {
                "intents": [{"intent": intent, "query": message, "confidence": 0.99,
                             "evidence": message}],
                "uncertain_intents": [], "finance_related": True,
                "intent_source": "deepseek", "classification_error": {},
            }

    return _C()


def test_market_overview_end_to_end_routes_to_market_insight(monkeypatch, overview_data):
    """"今天大盘怎么样"走市场洞察，不触发股票取数，也不产出个股结论。"""
    graph = build_supervisor_graph(
        SupervisorDependencies(
            classifier=_market_classifier("market_insight"),
            domain_runner=lambda context: build_market_domain_graph().invoke(
                {"context": context}
            )["domain_outcome"],
        )
    )
    result = graph.invoke(
        {"user_message": "今天大盘怎么样", "run_id": "run-1", "task_results": {}}
    )

    assert "上证指数" in result["final_response"]
    assert "validation error" not in result["final_response"]
    assert not result.get("stock_analysis")
    assert result["task_results"]["single:run-1:market_insight"]["domain"] == "market_insight"
