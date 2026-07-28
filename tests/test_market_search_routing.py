from finance_agent.core.orchestrator import AdvisorSystem


def make_state(message, thread_id):
    return {
        "user_message": message,
        "chat_history": [], "customer_id": "TEST", "task_plan": [],
        "business_state": {}, "user_profile": {}, "resolved_stocks": [],
        "candidate_stocks": [], "stock_search_error": "",
        "stock_resolution_error": "", "stock_data": {},
        "fundamental_analysis": {}, "allocation_result": {},
        "agent_response": "", "compliance_result": {}, "memory_context": "",
        "shared_memory_snapshot": {}, "thread_id": thread_id, "run_id": "run-1",
        "explicit_user_stock_codes": [], "stock_data_entries": [],
        "fundamental_entries": [], "detected_intents": [], "intent_results": {},
        "intent_source": "", "finance_related": True, "intent_stocks": {},
        "slot_tool_calls": [], "slot_tool_called": False,
        "slot_tool_source": "skipped", "slot_tool_error": "",
    }


def intent_plan(intent, mode, query="完全相同的文本"):
    return {
        "intent": intent,
        "query": query,
        "confidence": 0.99,
        "reason": "测试结构化执行计划",
        "execution_mode": mode,
        "requires_slot_extraction": False,
    }


def test_market_overview_mode_calls_market_search_without_query_keywords():
    system = AdvisorSystem()
    calls = []
    plan = intent_plan("market_query", "market_overview")
    system.supervisor.plan_tasks = lambda *_args, **_kwargs: {
        "intents": [plan],
        "finance_related": True,
        "intent_source": "model",
        "task_plan": ["compliance"],
    }
    system.stock_search.search_market_overview = (
        lambda query: calls.append(query) or "市场概览结果"
    )

    result = system.graph.invoke(
        make_state(plan["query"], "mode-market-overview"),
        config={"configurable": {"thread_id": "mode-market-overview"}},
    )

    assert calls == ["完全相同的文本"]
    assert result["intent_results"]["market_query"]["content"] == "市场概览结果"


def test_candidate_search_mode_calls_candidate_search_without_query_keywords():
    system = AdvisorSystem()
    calls = []
    plan = intent_plan("stock_recommendation", "candidate_search")
    candidate = {"code": "600000", "name": "浦发银行", "industry": "银行"}
    system.supervisor.plan_tasks = lambda *_args, **_kwargs: {
        "intents": [plan],
        "finance_related": True,
        "intent_source": "model",
        "task_plan": ["data_fetch", "fundamental_analysis", "compliance"],
    }
    system.stock_search.search = lambda query: calls.append(query) or [candidate]
    system.data_fetch_agent.handle_single_stock = lambda code: {
        "code": code,
        "quote": {"date": "2026-01-01", "price": 10, "change_pct": 1},
        "indicators": {"date": "2025-12-31", "roe": 10},
        "basic_info": {"name": "浦发银行", "industry": "银行"},
        "history": {"code": code, "dates": ["2025-01-01"], "close": [10]},
    }
    system.stock_agent.handle_single_stock = lambda code: {
        "code": code, "name": "浦发银行", "rating": "中性",
        "overall_score": 70, "summary": "基本面数据可供研究",
        "indicators": {}, "quote": {},
    }

    result = system.graph.invoke(
        make_state(plan["query"], "mode-candidate-search"),
        config={"configurable": {"thread_id": "mode-candidate-search"}},
    )

    assert calls == ["完全相同的文本"]
    assert result["candidate_stocks"] == [candidate]


def test_unsupported_market_plan_returns_error_without_legacy_slot_agent():
    system = AdvisorSystem()
    plan = intent_plan("market_query", "unsupported", "任意原始文本")
    system.supervisor.plan_tasks = lambda *_args, **_kwargs: {
        "intents": [plan],
        "finance_related": True,
        "intent_source": "zero_shot",
        "task_plan": ["compliance"],
    }

    assert not hasattr(system, "slot_agent")

    result = system.graph.invoke(
        make_state(plan["query"], "unsupported-market-plan"),
        config={"configurable": {"thread_id": "unsupported-market-plan"}},
    )

    assert result["intent_results"]["market_query"]["status"] == "error"
    assert "执行策略" in result["intent_results"]["market_query"]["content"]
