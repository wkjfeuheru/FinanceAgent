"""市场洞察意图：边界、三模式实数渲染与降级。

``market_insight`` 只回答市场级问题，绝不输出个股结论、推荐或配置。
取数经 ``tools.marketdata`` 注入，测试不联网。
"""

from __future__ import annotations

import threading

import pytest
from langgraph.checkpoint.memory import MemorySaver

import finance_agent.agents.market_insight as market_insight_module
from finance_agent.agents.market_insight import MarketInsightAgent
from finance_agent.agents.supervisor import ManagerAgent
from finance_agent.contracts.adapters import normalize_dispatch_plan
from finance_agent.contracts.schema.enums import IntentKind
from finance_agent.orchestrator.orchestrator import AdvisorSystem


def test_market_insight_routes_to_its_own_expert():
    plan = normalize_dispatch_plan(
        [{"intent": "market_insight", "query": "今天大盘怎么样", "confidence": 0.99,
          "execution_mode": "market_overview", "evidence": "今天大盘怎么样"}],
        "今天大盘怎么样",
    )

    assert len(plan.tasks) == 1
    task = plan.tasks[0]
    assert task.intent is IntentKind.MARKET_INSIGHT
    assert task.expert_name == "market_insight"


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
    monkeypatch.setattr(market_insight_module, "get_market_overview_data", lambda: payload)
    return payload


def test_overview_mode_renders_real_numbers(overview_data):
    state = MarketInsightAgent().invoke({
        "requirement": "今天大盘怎么样", "current_task_intent": "market_insight",
        "task_context": {"execution_mode": "market_overview"}, "intent_results": {},
    })

    result = state["intent_results"]["market_insight"]
    assert result["status"] == "success"
    assert "上证指数" in result["content"]
    assert "3,888.11" in result["content"]
    assert "-1.18%" in result["content"]
    assert "上涨 604 家" in result["content"]
    assert state["market_insight"]["mode"] == "market_overview"
    # 硬边界：不得产出任何个股结论字段。
    assert "stock_analysis" not in state
    assert "analysis_results" not in state


def test_sentiment_mode_renders_breadth(monkeypatch):
    monkeypatch.setattr(market_insight_module, "get_market_sentiment_data", lambda: {
        "as_of": "2026-09-11",
        "breadth": {"advancing": 604, "declining": 4567, "limit_up": 40,
                    "limit_down": 21, "flat": 36, "suspended": 12, "activity": 11.57},
        "benchmark": {"name": "上证指数", "close": 3888.11, "pct_chg": -1.18},
        "limitations": [],
        "note": "",
    })

    state = MarketInsightAgent().invoke({
        "requirement": "市场情绪如何", "current_task_intent": "market_insight",
        "task_context": {"execution_mode": "market_sentiment"}, "intent_results": {},
    })

    content = state["intent_results"]["market_insight"]["content"]
    assert "市场情绪" in content
    assert "偏弱" in content          # 下跌多于上涨
    assert "11.57%" in content
    assert state["market_insight"]["mode"] == "market_sentiment"


def test_capital_flow_mode_renders_margin_and_holdings(monkeypatch):
    """capital_flow 以融资融券（日频主指标）+ 北向持股市值（季度参考）呈现。"""
    monkeypatch.setattr(market_insight_module, "get_capital_flow_data", lambda: {
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

    state = MarketInsightAgent().invoke({
        "requirement": "资金面如何", "current_task_intent": "market_insight",
        "task_context": {"execution_mode": "capital_flow"}, "intent_results": {},
    })

    content = state["intent_results"]["market_insight"]["content"]
    assert "融资融券（两市合计，2026-09-10）" in content
    assert "26,171.76 亿元" in content        # 融资余额
    assert "26,463.68 亿元" in content        # 两融余额
    assert "北向持股市值（2026-06-30，季度披露）" in content
    assert "31,023.75 亿元" in content
    assert state["market_insight"]["mode"] == "capital_flow"


def test_capital_flow_lists_missing_source_instead_of_faking(monkeypatch):
    monkeypatch.setattr(market_insight_module, "get_capital_flow_data", lambda: {
        "as_of": "2026-09-10",
        "margin": {"as_of": "2026-09-10", "financing_balance_yi": 26171.760561},
        "northbound_holdings": {},
        "limitations": ["northbound_holdings"],
        "note": "融资融券为两市合计、交易所日频披露；北向持股市值为季度披露，非实时。",
    })

    state = MarketInsightAgent().invoke({
        "requirement": "资金面如何", "current_task_intent": "market_insight",
        "task_context": {"execution_mode": "capital_flow"}, "intent_results": {},
    })

    result = state["intent_results"]["market_insight"]
    assert result["status"] == "partial"
    assert "northbound_holdings" in result["content"]


def test_capital_flow_degrades_when_all_missing(monkeypatch):
    monkeypatch.setattr(market_insight_module, "get_capital_flow_data", lambda: {
        "as_of": "", "margin": {}, "northbound_holdings": {},
        "limitations": ["margin_summary", "northbound_holdings"], "note": "",
    })

    state = MarketInsightAgent().invoke({
        "requirement": "资金面如何", "current_task_intent": "market_insight",
        "task_context": {"execution_mode": "capital_flow"}, "intent_results": {},
    })

    assert state["intent_results"]["market_insight"]["status"] == "degraded"


def test_partial_failures_are_disclosed_not_faked(monkeypatch):
    monkeypatch.setattr(market_insight_module, "get_market_overview_data", lambda: {
        "as_of": "2026-09-11",
        "indices": [{"symbol": "sh000001", "name": "上证指数", "close": 3888.11,
                     "pct_chg": -1.18}],
        "breadth": {},
        "limitations": ["market_breadth"],
        "note": "",
    })

    state = MarketInsightAgent().invoke({
        "requirement": "今天大盘怎么样", "current_task_intent": "market_insight",
        "task_context": {"execution_mode": "market_overview"}, "intent_results": {},
    })

    result = state["intent_results"]["market_insight"]
    assert result["status"] == "partial"
    assert "限制与提示" in result["content"]
    assert "market_breadth" in result["content"]


def test_all_data_missing_degrades_honestly(monkeypatch):
    monkeypatch.setattr(market_insight_module, "get_market_overview_data", lambda: {
        "as_of": "", "indices": [], "breadth": {}, "limitations": ["market_breadth"], "note": "",
    })

    state = MarketInsightAgent().invoke({
        "requirement": "今天大盘怎么样", "current_task_intent": "market_insight",
        "task_context": {"execution_mode": "market_overview"}, "intent_results": {},
    })

    result = state["intent_results"]["market_insight"]
    assert result["status"] == "degraded"
    assert "暂不可用" in result["content"]


def test_market_insight_agent_rejects_unknown_mode():
    state = MarketInsightAgent().invoke({
        "requirement": "外汇", "current_task_intent": "market_insight",
        "task_context": {"execution_mode": "fx_flow"}, "intent_results": {},
    })

    assert state["intent_results"]["market_insight"]["status"] == "degraded"
    assert "暂不支持" in state["intent_results"]["market_insight"]["content"]


def test_market_overview_renders_turnover_and_range(monkeypatch):
    """大盘概览盘活已有数据：成交额与近 5/20 日区间涨跌。"""
    monkeypatch.setattr(market_insight_module, "get_market_overview_data", lambda: {
        "as_of": "2026-09-11",
        "indices": [{
            "symbol": "sh000001", "name": "上证指数", "close": 3888.11, "pct_chg": -1.18,
            "amount": 512300000000.0, "pct_5d": -2.3, "pct_20d": 1.75,
        }],
        "breadth": {}, "limitations": [], "note": "指数为最近交易日收盘。",
    })

    state = MarketInsightAgent().invoke({
        "requirement": "大盘", "current_task_intent": "market_insight",
        "task_context": {"execution_mode": "market_overview"}, "intent_results": {},
    })

    content = state["intent_results"]["market_insight"]["content"]
    assert "成交额 5,123.00 亿元" in content
    assert "近5日 -2.30%" in content
    assert "近20日 +1.75%" in content
    # note 现在三个模式统一渲染。
    assert "数据说明：指数为最近交易日收盘。" in content


def test_capital_flow_renders_day_over_day_change(monkeypatch):
    """资金面盘活已有数据：融资余额日环比。"""
    monkeypatch.setattr(market_insight_module, "get_capital_flow_data", lambda: {
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

    state = MarketInsightAgent().invoke({
        "requirement": "资金面", "current_task_intent": "market_insight",
        "task_context": {"execution_mode": "capital_flow"}, "intent_results": {},
    })

    content = state["intent_results"]["market_insight"]["content"]
    assert "融资余额较上日 +71.76 亿元" in content


def test_unavailable_message_is_mode_specific(monkeypatch):
    """整体降级文案按模式区分，资金面不得误报"指数与宽度"。"""
    monkeypatch.setattr(market_insight_module, "get_capital_flow_data", lambda: {
        "as_of": "", "margin": {}, "northbound_holdings": {},
        "limitations": ["margin_summary", "northbound_holdings"], "note": "",
    })

    state = MarketInsightAgent().invoke({
        "requirement": "资金面", "current_task_intent": "market_insight",
        "task_context": {"execution_mode": "capital_flow"}, "intent_results": {},
    })

    content = state["intent_results"]["market_insight"]["content"]
    assert "融资融券" in content
    assert "市场宽度" not in content


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
    monkeypatch.setattr(market_insight_module, "get_policy_events_data", lambda: dict(_POLICY_PAYLOAD))
    agent = MarketInsightAgent(interpreter=_FakeInterpreter(text="流动性边际宽松，利好市场风险偏好。"))

    state = agent.invoke({
        "requirement": "政策有什么影响", "current_task_intent": "market_insight",
        "task_context": {"execution_mode": "policy_impact"}, "intent_results": {},
    })

    result = state["intent_results"]["market_insight"]
    assert result["status"] == "success"
    assert "央行开展逆回购操作" in result["content"]
    assert "[货币政策]" in result["content"]
    assert "影响解读：" in result["content"]
    assert "流动性边际宽松" in result["content"]
    assert state["market_insight"]["mode"] == "policy_impact"
    # 硬边界不变。
    assert "stock_analysis" not in state


def test_policy_impact_falls_back_to_plain_list_on_llm_failure(monkeypatch):
    """LLM 解读失败时回退纯事件清单并标注，不伪造解读。"""
    monkeypatch.setattr(market_insight_module, "get_policy_events_data", lambda: dict(_POLICY_PAYLOAD))
    agent = MarketInsightAgent(interpreter=_FakeInterpreter(error=RuntimeError("llm down")))

    state = agent.invoke({
        "requirement": "政策有什么影响", "current_task_intent": "market_insight",
        "task_context": {"execution_mode": "policy_impact"}, "intent_results": {},
    })

    result = state["intent_results"]["market_insight"]
    assert "央行开展逆回购操作" in result["content"]      # 清单仍在
    assert "影响解读暂不可用" in result["content"]
    assert result["status"] == "partial"                  # 记入限制
    assert "policy_interpretation" in result["content"]


def test_policy_impact_reports_empty_state_honestly(monkeypatch):
    """取数成功但无政策类事件时，诚实返回空态而非硬凑。"""
    monkeypatch.setattr(market_insight_module, "get_policy_events_data", lambda: {
        "as_of": "", "events": [], "categories_summary": {},
        "window_days": 3, "limitations": [], "note": "",
    })

    state = MarketInsightAgent().invoke({
        "requirement": "政策有什么影响", "current_task_intent": "market_insight",
        "task_context": {"execution_mode": "policy_impact"}, "intent_results": {},
    })

    result = state["intent_results"]["market_insight"]
    assert result["status"] == "success"
    assert "未筛选出政策类事件" in result["content"]


def test_policy_impact_degrades_when_news_source_unavailable(monkeypatch):
    monkeypatch.setattr(market_insight_module, "get_policy_events_data", lambda: {
        "as_of": "", "events": [], "categories_summary": {},
        "window_days": 3, "limitations": ["policy_news"], "note": "",
    })

    state = MarketInsightAgent().invoke({
        "requirement": "政策有什么影响", "current_task_intent": "market_insight",
        "task_context": {"execution_mode": "policy_impact"}, "intent_results": {},
    })

    result = state["intent_results"]["market_insight"]
    assert result["status"] == "degraded"
    assert "财经快讯" in result["content"]


def test_policy_interpretation_rejects_sensitive_output():
    """解读命中敏感词时抛异常（由上层回退纯清单）。"""
    from finance_agent.agents.market_insight import PolicyImpactInterpreter

    class _FakeChain:
        def invoke(self, _):
            return "这只股票必涨，建议买入。"

    interpreter = PolicyImpactInterpreter()
    interpreter._chain = _FakeChain()

    with pytest.raises(ValueError):
        interpreter.interpret([{"title": "某政策"}], "2026-09-13", 3)


def _make_system(monkeypatch, *, classifier_intents):
    system = object.__new__(AdvisorSystem)
    system.checkpointer = MemorySaver()
    system.manager = ManagerAgent()
    system.manager._intent_classifier = type(
        "C", (), {"classify": lambda self, *a, **k: {
            "finance_related": True, "intents": classifier_intents,
        }},
    )()
    system.stock_agent = type("S", (), {"agent_name": "stock_analysis"})()
    system.market_insight_agent = MarketInsightAgent()
    system.product_agent = type("P", (), {"invoke": lambda self, s: s})()
    system.casual_chat_agent = type("C", (), {"invoke": lambda self, s: s})()
    system.slot_extractor = type("Slots", (), {"extract": lambda self, s: s})()
    system._progress_context = type("Context", (), {})()
    system._progress_callbacks = {}
    system._progress_lock = threading.Lock()
    system._trace_lock = threading.Lock()
    system._trace_sequences = {}
    system._workflow_lock = threading.RLock()
    system._stop_requests = {}
    system._active_runs = {}
    system._stop_lock = threading.Lock()
    system.audit = type("_NoopAudit", (), {"is_available": lambda self: False})()
    system._trace_agent = lambda *a, **k: None
    system._emit_progress = lambda *a, **k: None
    return system


def test_market_overview_end_to_end_routes_to_market_insight(monkeypatch, overview_data):
    """"今天大盘怎么样"走市场洞察，不触发股票取数，也不产出个股结论。"""
    system = _make_system(monkeypatch, classifier_intents=[{
        "intent": "market_insight", "query": "今天大盘怎么样", "confidence": 0.99,
        "execution_mode": "market_overview", "evidence": "今天大盘怎么样",
    }])
    graph = system._build_graph()
    result = graph.invoke(
        {"user_message": "今天大盘怎么样", "completed_experts": [], "intent_results": {}},
        config={"configurable": {"thread_id": "market-overview-e2e"}},
    )

    assert "上证指数" in result["agent_response"]
    assert "validation error" not in result["agent_response"]
    assert not result.get("stock_analysis")
    assert result["task_results"]["task-1"].expert_name == "market_insight"
