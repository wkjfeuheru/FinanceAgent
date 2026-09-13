"""运行时控制回归测试：停止生成、澄清流程、admin 清全库门控。"""

import asyncio

import pytest
from fastapi import HTTPException

from finance_agent.agents.supervisor import ManagerAgent


class _FakeClassifier:
    def __init__(self, payload):
        self.payload = payload

    def classify(self, *args, **kwargs):
        return self.payload


def test_request_stop_and_is_stopped():
    from finance_agent.orchestrator.orchestrator import AdvisorSystem

    system = object.__new__(AdvisorSystem)
    system._stop_requests = {}
    system._active_runs = {}
    system._stop_lock = __import__("threading").Lock()

    system._active_runs["run-1"] = "conv-1"
    assert system.request_stop(run_id="run-1") is True
    assert system._is_stopped("conv-1") is True
    assert system._is_stopped("conv-2") is False
    assert system.request_stop(conversation_id="conv-2") is True
    assert system._is_stopped("conv-2") is True
    assert system.request_stop() is False  # 无标识不记录


def test_clarification_writes_uncertain_intents():
    manager = ManagerAgent()
    manager._intent_classifier = _FakeClassifier({
        "intents": [{
            "intent": "stock_recommendation",
            "query": "那只股票",
            "confidence": 0.5,
            "reason": "低置信度",
            "evidence": "那只股票",
            "execution_mode": "candidate_search",
            "clarification_question": "您想分析具体哪只股票？",
        }],
        "finance_related": True,
    })
    state = {"user_message": "帮我看看那只股票"}
    dispatch = manager.dispatch_tasks(state)

    assert dispatch == []
    assert len(state["uncertain_intents"]) == 1
    assert state["uncertain_intents"][0]["clarification_question"] == "您想分析具体哪只股票？"


def test_classification_marks_error_when_no_valid_intents():
    """模型返回了 intents 但全部被过滤：必须标记分类失败（否则落含糊回复）。"""
    manager = ManagerAgent()
    manager._intent_classifier = _FakeClassifier({
        "intents": [{
            "intent": "unknown_intent",          # 非法意图，_validate 会丢弃
            "query": "x", "confidence": 0.99, "evidence": "x",
        }],
        "finance_related": True,
    })

    result = manager.classify_intents("随便问问")

    assert result["intents"] == []
    assert result["classification_error"], "空有效意图必须带非空错误，供编排层走兜底"
    assert result["classification_error"]["cause"] == "no_valid_intents"


def test_stale_clarification_does_not_block_next_turn():
    """回归 P0：上一轮的反问不得短路本轮合成（专家已执行却被丢弃）。

    构造两轮：第一轮低置信度给澄清；第二轮高置信度正常分派。第二轮必须
    产出专家内容，而不是回放第一轮的旧澄清问题。
    """
    import threading

    from langgraph.checkpoint.memory import MemorySaver

    import finance_agent.agents.market_insight as market_insight_module
    from finance_agent.agents.market_insight import MarketInsightAgent
    from finance_agent.orchestrator.orchestrator import AdvisorSystem

    market_insight_module.get_market_overview_data = lambda: {
        "as_of": "2026-09-11",
        "indices": [{"symbol": "sh000001", "name": "上证指数",
                     "close": 3888.11, "pct_chg": -1.18}],
        "breadth": {}, "limitations": [], "note": "",
    }

    turn = {"n": 0}

    class _TwoTurnClassifier:
        def classify(self, *args, **kwargs):
            turn["n"] += 1
            if turn["n"] == 1:
                return {"finance_related": True, "intents": [{
                    "intent": "market_insight", "query": "看看市场", "confidence": 0.5,
                    "execution_mode": "market_overview", "evidence": "看看市场",
                    "clarification_question": "您想看大盘还是市场情绪？",
                }]}
            return {"finance_related": True, "intents": [{
                "intent": "market_insight", "query": "今天大盘怎么样", "confidence": 0.99,
                "execution_mode": "market_overview", "evidence": "今天大盘怎么样",
            }]}

    system = object.__new__(AdvisorSystem)
    system.checkpointer = MemorySaver()
    system.manager = ManagerAgent()
    system.manager._intent_classifier = _TwoTurnClassifier()
    system.stock_agent = object()
    system.market_insight_agent = MarketInsightAgent()
    system.product_agent = type("P", (), {"invoke": lambda self, s: s})()
    system.casual_chat_agent = type("C", (), {"invoke": lambda self, s: s})()
    system.slot_extractor = type("Slots", (), {"extract": lambda self, s: s})()
    system._progress_context = type("Ctx", (), {})()
    system._progress_callbacks = {}
    system._progress_lock = threading.Lock()
    system._trace_lock = threading.Lock()
    system._trace_sequences = {}
    system._workflow_lock = threading.RLock()
    system._stop_requests = {}
    system._active_runs = {}
    system._stop_lock = threading.Lock()
    system.audit = type("A", (), {
        "is_available": lambda self: False,
        "create_run": lambda *a, **k: None,
        "complete_run": lambda *a, **k: None,
        "upsert_expert_result": lambda *a, **k: None,
    })()
    system._trace_agent = lambda *a, **k: None
    system._emit_progress = lambda *a, **k: None

    graph = system._build_graph()
    config = {"configurable": {"thread_id": "stale-clarify-regression"}}

    turn1 = graph.invoke(
        {"user_message": "看看市场", "completed_experts": [], "intent_results": {}},
        config=config,
    )
    assert "需要您进一步确认" in turn1["agent_response"]

    turn2 = graph.invoke(
        {"user_message": "今天大盘怎么样", "completed_experts": [], "intent_results": {}},
        config=config,
    )
    assert "需要您进一步确认" not in turn2["agent_response"], "旧澄清问题不得短路本轮"
    assert "上证指数" in turn2["agent_response"]


def test_handle_message_output_includes_stock_structured_fields(monkeypatch):
    """回归 P1a：API 输出必须携带 analysis_results/technical_analysis 等结构化字段。

    此前输出投影漏了这几项，导致 /api/chat 与 SSE 都拿不到专家算出的研究结论
    （前端 MessageList 渲染的正是 analysis_results）。
    """
    import threading

    from finance_agent.contracts import RunStatus
    from finance_agent.orchestrator.orchestrator import AdvisorSystem

    system = object.__new__(AdvisorSystem)
    system._workflow_lock = threading.RLock()
    system._stop_lock = threading.Lock()
    system._stop_requests = {}
    system._active_runs = {}
    system._progress_lock = threading.Lock()
    system._progress_callbacks = {}
    system._trace_lock = threading.Lock()
    system._trace_sequences = {}
    system._progress_context = type("Ctx", (), {"callback": None})()
    system.memory = type("M", (), {
        "window_size": 10,
        "load_context": lambda self, c, conv, fb: {
            "profile": {}, "context_text": "", "sliding_window": [],
        },
        "append_window_message": lambda *a, **k: None,
        "update_profile_from_result": lambda *a, **k: None,
        "update_recent_summary": lambda *a, **k: None,
    })()
    system.audit = type("A", (), {
        "is_available": lambda self: False,
        "create_run": lambda *a, **k: None,
        "complete_run": lambda *a, **k: None,
        "upsert_expert_result": lambda *a, **k: None,
    })()
    system._update_conversation_meta = lambda *a, **k: None
    system.get_checkpoint_conversation_messages = lambda *a, **k: []
    system._emit_progress = lambda *a, **k: None
    system._trace_agent = lambda *a, **k: None
    monkeypatch.setattr(
        "finance_agent.orchestrator.orchestrator.get_database",
        lambda: type("DB", (), {
            "append_conversation_message": lambda *a, **k: None,
        })(),
    )

    enriched = {
        "agent_response": "已完成 600519 的分析。",
        "task_plan": ["stock_analysis"],
        "stock_data": {"600519": {"basic_info": {"name": "贵州茅台"}}},
        "stock_analysis": {"600519": {"rating": "推荐"}},
        "technical_analysis": {"600519": {"trend": "up"}},
        "fundamental_analysis": {"600519": {"pe": 25.0}},
        "analysis_results": [{"action": "关注", "rule_version": "research_rules/v1.2"}],
        "run_status": RunStatus.COMPLETED,
        "facts": [],
    }
    system.graph = type("G", (), {"invoke": lambda self, state, config=None: enriched})()

    output = system.handle_message("分析600519", conversation_id="proj-test")

    assert output["analysis_results"][0]["rule_version"] == "research_rules/v1.2"
    assert output["technical_analysis"] == {"600519": {"trend": "up"}}
    assert output["fundamental_analysis"] == {"600519": {"pe": 25.0}}


def test_clear_records_admin_gate(monkeypatch):
    from finance_agent.api import routes as r

    monkeypatch.setattr(r, "ADMIN_CUSTOMER_IDS", set())

    class _FakeRequest:
        headers = {"Authorization": "Bearer good-token"}

    class _FakeStore:
        def verify_token(self, token):
            return "CUST000001"

    monkeypatch.setattr(r, "get_user_store", lambda: _FakeStore())

    with pytest.raises(HTTPException) as exc:
        asyncio.run(r.clear_records(_FakeRequest(), customer_id=None, keep_users=True))
    assert exc.value.status_code == 403
