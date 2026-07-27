from finance_agent.core.orchestrator import AdvisorSystem


def make_state(message, thread_id):
    return {
        "user_message": message,
        "chat_history": [], "customer_id": "TEST", "task_plan": [],
        "business_state": {}, "user_profile": {}, "resolved_stocks": [],
        "candidate_stocks": [], "stock_search_error": "", "stock_resolution_error": "",
        "stock_data": {}, "fundamental_analysis": {}, "allocation_result": {},
        "agent_response": "", "compliance_result": {}, "memory_context": "",
        "shared_memory_snapshot": {}, "thread_id": thread_id, "run_id": "run-1",
        "explicit_user_stock_codes": [], "stock_data_entries": [],
        "fundamental_entries": [], "detected_intents": [], "intent_results": {},
        "intent_source": "", "finance_related": True, "intent_stocks": {},
        "slot_tool_calls": [], "slot_tool_called": False,
        "slot_tool_source": "skipped", "slot_tool_error": "",
    }


def test_recommendation_allocation_and_chat_are_combined():
    system = AdvisorSystem()
    system.supervisor.plan_tasks = lambda *_args, **_kwargs: {
        "intents": [
            {"intent": "stock_recommendation", "query": "推荐两只银行股", "confidence": 0.95, "reason": "推荐"},
            {"intent": "asset_allocation", "query": "将10万元配置到推荐股票", "confidence": 0.94, "reason": "配置"},
            {"intent": "casual_chat", "query": "回应投资焦虑", "confidence": 0.9, "reason": "情绪"},
        ],
        "finance_related": True,
        "intent_source": "model",
        "task_plan": [
            "data_fetch", "fundamental_analysis", "asset_allocation",
            "casual_chat", "compliance",
        ],
    }
    system.supervisor.decide_slot_tool_calls = lambda *_args, **_kwargs: [{
        "name": "extract_finance_slots",
        "args": {
            "intent": "asset_allocation",
            "query": "将10万元配置到推荐股票",
        },
        "id": "tool-1",
    }]
    system.supervisor.chat = lambda *_args, **_kwargs: "投资出现焦虑很常见，可以先复盘风险承受能力。"
    system.slot_agent.extract_slots = lambda *_args, **_kwargs: {
        "user_profile": {
            "risk_preference": "R2 中低风险", "budget_amount": 100000,
            "holding_period": "1年", "stock_codes": [],
        },
        "resolved_stocks": [],
        "explicit_stock_codes": [],
    }
    candidates = [
        {"code": "600000", "name": "浦发银行", "industry": "银行"},
        {"code": "600036", "name": "招商银行", "industry": "银行"},
    ]
    system.stock_search.search = lambda *_args, **_kwargs: candidates
    system.data_fetch_agent.handle_single_stock = lambda code: {
        "code": code,
        "quote": {"date": "2026-01-01", "price": 10, "change_pct": 1},
        "indicators": {"date": "2025-12-31", "roe": 10},
        "basic_info": {"name": code, "industry": "银行"},
        "history": {"code": code, "dates": ["2025-01-01"], "close": [10]},
    }
    system.fundamental_agent.handle_single_stock = lambda code: {
        "code": code, "name": code, "rating": "中性", "overall_score": 70,
        "summary": "基本面数据可供进一步研究", "indicators": {}, "quote": {},
    }

    def allocation_response(**_kwargs):
        system.shared_memory.publish_fact(
            "allocation_result", {"weights": {"600000": 0.5, "600036": 0.5}},
            source="test",
        )
        return "两只候选股票各配置50%。"

    system.allocation_agent.handle = allocation_response
    system._synthesize_response = lambda state: system._compose_intent_draft(state)

    state = {
        "user_message": "最近有些焦虑，推荐两只银行股并用10万元配置",
        "chat_history": [], "customer_id": "TEST", "task_plan": [],
        "business_state": {}, "user_profile": {}, "resolved_stocks": [],
        "candidate_stocks": [], "stock_search_error": "", "stock_resolution_error": "",
        "stock_data": {}, "fundamental_analysis": {}, "allocation_result": {},
        "agent_response": "", "compliance_result": {}, "memory_context": "",
        "shared_memory_snapshot": {}, "thread_id": "multi-intent-test", "run_id": "run-1",
        "explicit_user_stock_codes": [], "stock_data_entries": [], "fundamental_entries": [],
        "detected_intents": [], "intent_results": {}, "intent_source": "",
        "finance_related": True, "intent_stocks": {},
        "slot_tool_calls": [], "slot_tool_called": False,
        "slot_tool_source": "skipped", "slot_tool_error": "",
    }
    result = system.graph.invoke(
        state, config={"configurable": {"thread_id": "multi-intent-test"}},
    )

    assert set(result["intent_results"]) == {
        "stock_recommendation", "asset_allocation", "casual_chat",
    }
    assert result["intent_stocks"]["stock_recommendation"] == candidates
    assert result["slot_tool_called"] is True
    assert "slot_extraction" in result["task_plan"]
    assert "交流回应" in result["agent_response"]
    assert "候选标的研究" in result["agent_response"]
    assert "资产配置" in result["agent_response"]


def test_malformed_model_tool_calls_use_deterministic_fallback():
    system = AdvisorSystem()
    query = "用10万元做稳健配置"
    system.supervisor.plan_tasks = lambda *_args, **_kwargs: {
        "intents": [{
            "intent": "asset_allocation", "query": query,
            "confidence": 0.95, "reason": "配置",
        }],
        "finance_related": True,
        "intent_source": "model",
        "task_plan": ["asset_allocation", "compliance"],
    }
    system.supervisor.decide_slot_tool_calls = lambda *_args, **_kwargs: [
        None,
        "bad-call",
        {"name": "extract_finance_slots", "args": "bad-args"},
    ]
    calls = []

    def extract_slots(message, **_kwargs):
        calls.append(message)
        return {
            "user_profile": {
                "risk_preference": "R2 中低风险",
                "budget_amount": 100000,
                "holding_period": "1年",
                "investment_goal": "稳健增值",
                "stock_codes": [],
            },
            "resolved_stocks": [],
            "explicit_stock_codes": [],
        }

    system.slot_agent.extract_slots = extract_slots

    result = system.graph.invoke(
        make_state(query, "malformed-tool-calls"),
        config={"configurable": {"thread_id": "malformed-tool-calls"}},
    )

    assert result["slot_tool_source"] == "deterministic_fallback"
    assert result["slot_tool_called"] is True
    assert calls == [query]
