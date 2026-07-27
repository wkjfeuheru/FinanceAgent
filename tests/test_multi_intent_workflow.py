import pytest

import finance_agent.core.orchestrator as orchestrator_module
from finance_agent.core.orchestrator import AdvisorSystem
from finance_agent.tools.finance_slots import FinanceSlotsExtractor


def test_advisor_system_exposes_slot_tool_runtime_not_slot_agent():
    system = AdvisorSystem()

    assert isinstance(system.finance_slots_extractor, FinanceSlotsExtractor)
    assert not hasattr(system, "slot_agent")


def test_classifier_failure_returns_explicit_error_instead_of_chat_response():
    system = AdvisorSystem()

    class FailedClassifier:
        def predict(self, *_args, **_kwargs):
            raise TimeoutError("timed out")

    system.supervisor._zero_shot_classifier = FailedClassifier()
    system.compliance_agent.review = lambda **_kwargs: {"pass": True, "reason": ""}
    state = make_state("列出中际旭创的一些基本面指标", "classification-error")

    result = system.graph.invoke(
        state,
        config={"configurable": {"thread_id": "classification-error"}},
    )

    assert result["intent_source"] == "classification_error"
    assert result["detected_intents"] == []
    assert result["agent_response"] == "意图识别暂时不可用，请稍后重试。"


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


def test_pending_state_does_not_override_supervisor_plan_from_cancel_keyword():
    system = AdvisorSystem()
    query = "取消"
    system.supervisor.plan_tasks = lambda *_args, **_kwargs: {
        "intents": [{
            "intent": "market_query",
            "query": query,
            "confidence": 0.99,
            "reason": "监督者确认市场概览",
            "execution_mode": "market_overview",
            "requires_slot_extraction": False,
        }],
        "finance_related": True,
        "intent_source": "model",
        "task_plan": ["compliance"],
    }
    system.stock_search.search_market_overview = lambda _query: "监督者计划已执行"
    state = make_state(query, "pending-plan-authority")
    state["business_state"] = {
        "status": "waiting_for_input",
        "intent": "asset_allocation",
        "missing_fields": ["budget_amount"],
    }

    result = system.graph.invoke(
        state,
        config={"configurable": {"thread_id": "pending-plan-authority"}},
    )

    assert [item["intent"] for item in result["detected_intents"]] == ["market_query"]
    assert result["intent_results"]["market_query"]["content"] == "监督者计划已执行"


def test_pending_allocation_clears_for_supervisor_conversation_plan():
    system = AdvisorSystem()
    query = "这件事到此为止"
    system.supervisor.plan_tasks = lambda *_args, **_kwargs: {
        "intents": [{
            "intent": "casual_chat",
            "query": query,
            "confidence": 0.99,
            "reason": "终止等待任务",
            "execution_mode": "conversation",
            "requires_slot_extraction": False,
        }],
        "finance_related": True,
        "intent_source": "model",
        "task_plan": ["casual_chat", "compliance"],
    }
    system.supervisor.chat = lambda *_args, **_kwargs: "已结束此前的配置任务。"
    state = make_state(query, "pending-plan-stop")
    state["business_state"] = {
        "status": "waiting_for_input",
        "intent": "asset_allocation",
        "missing_fields": ["budget_amount"],
    }

    result = system.graph.invoke(
        state,
        config={"configurable": {"thread_id": "pending-plan-stop"}},
    )

    assert result["business_state"] == {}
    assert "asset_allocation" not in result["task_plan"]


def test_market_overview_survives_allocation_waiting_state():
    system = AdvisorSystem()
    market_query = "查看整体方向"
    allocation_query = "再安排这笔资金"
    system.supervisor.plan_tasks = lambda *_args, **_kwargs: {
        "intents": [
            {
                "intent": "market_query", "query": market_query,
                "confidence": 0.99, "reason": "市场概览",
                "execution_mode": "market_overview",
                "requires_slot_extraction": False,
            },
            {
                "intent": "asset_allocation", "query": allocation_query,
                "confidence": 0.99, "reason": "配置",
                "execution_mode": "allocation",
                "requires_slot_extraction": True,
            },
        ],
        "finance_related": True,
        "intent_source": "model",
        "task_plan": [
            "data_fetch", "fundamental_analysis", "asset_allocation", "compliance",
        ],
    }
    system.supervisor.decide_slot_tool_calls = lambda *_args, **_kwargs: [{
        "name": "extract_finance_slots",
        "args": {"intent": "asset_allocation", "query": allocation_query},
        "id": "allocation-slots",
    }]
    system.finance_slots_extractor.extract_slots = lambda *_args, **_kwargs: {
        "user_profile": {}, "resolved_stocks": [], "explicit_stock_codes": [],
    }
    system.stock_search.search_market_overview = lambda _query: "市场概览成功"

    result = system.graph.invoke(
        make_state("组合请求", "overview-allocation-waiting"),
        config={"configurable": {"thread_id": "overview-allocation-waiting"}},
    )

    assert result["intent_results"]["market_query"] == {
        "status": "success", "content": "市场概览成功",
    }
    assert result["intent_results"]["asset_allocation"]["status"] == "waiting_for_input"
    assert "data_fetch" not in result["task_plan"]
    assert "fundamental_analysis" not in result["task_plan"]


def test_allocation_uses_its_own_stocks_instead_of_query_keywords():
    system = AdvisorSystem()
    recommendation_query = "给出一组研究对象"
    allocation_query = "另一笔十万元按稳健方式处理"
    system.supervisor.plan_tasks = lambda *_args, **_kwargs: {
        "intents": [
            {
                "intent": "stock_recommendation", "query": recommendation_query,
                "confidence": 0.99, "reason": "候选搜索",
                "execution_mode": "candidate_search",
                "requires_slot_extraction": False,
            },
            {
                "intent": "asset_allocation", "query": allocation_query,
                "confidence": 0.99, "reason": "独立配置",
                "execution_mode": "allocation",
                "requires_slot_extraction": True,
            },
        ],
        "finance_related": True,
        "intent_source": "model",
        "task_plan": [
            "data_fetch", "fundamental_analysis", "asset_allocation", "compliance",
        ],
    }
    system.supervisor.decide_slot_tool_calls = lambda *_args, **_kwargs: [{
        "name": "extract_finance_slots",
        "args": {"intent": "asset_allocation", "query": allocation_query},
        "id": "allocation-own-stocks",
    }]
    allocation_stocks = [
        {"code": "600519", "name": "贵州茅台", "industry": "白酒"},
        {"code": "000858", "name": "五粮液", "industry": "白酒"},
    ]
    recommendation_stocks = [
        {"code": "600000", "name": "浦发银行", "industry": "银行"},
        {"code": "600036", "name": "招商银行", "industry": "银行"},
    ]
    system.finance_slots_extractor.extract_slots = lambda *_args, **_kwargs: {
        "user_profile": {
            "risk_preference": "R2 中低风险", "budget_amount": 100000,
            "holding_period": "1年", "investment_goal": "稳健增值",
        },
        "resolved_stocks": allocation_stocks,
        "explicit_stock_codes": ["600519", "000858"],
    }
    system.stock_search.search = lambda *_args, **_kwargs: recommendation_stocks
    system.data_fetch_agent.handle_single_stock = lambda code: {
        "code": code,
        "quote": {"date": "2026-01-01", "price": 10, "change_pct": 1},
        "indicators": {"date": "2025-12-31", "roe": 10},
        "basic_info": {"name": code, "industry": "测试"},
        "history": {"code": code, "dates": ["2025-01-01"], "close": [10]},
    }
    system.fundamental_agent.handle_single_stock = lambda code: {
        "code": code, "name": code, "rating": "中性", "overall_score": 70,
        "summary": "基本面数据可供研究", "indicators": {}, "quote": {},
    }
    allocation_codes = []

    def capture_allocation(**_kwargs):
        profile = system.shared_memory.query("user_profile", {}) or {}
        allocation_codes.extend(profile.get("stock_codes", []))
        system.shared_memory.publish_fact(
            "allocation_result", {"weights": {code: 0.5 for code in allocation_codes}},
            source="test",
        )
        return "配置完成"

    system.allocation_agent.handle = capture_allocation

    system.graph.invoke(
        make_state("组合请求", "isolated-allocation-stocks"),
        config={"configurable": {"thread_id": "isolated-allocation-stocks"}},
    )

    assert allocation_codes == ["600519", "000858"]


def test_empty_task_plan_never_authorizes_asset_allocation():
    state = make_state("任意文本", "empty-plan")
    state["resolved_stocks"] = [
        {"code": "600519", "name": "贵州茅台"},
        {"code": "000858", "name": "五粮液"},
    ]

    assert AdvisorSystem._route_after_fundamental_plan(state) == "compliance"


def test_recommendation_allocation_and_chat_are_combined():
    system = AdvisorSystem()
    system.supervisor.plan_tasks = lambda *_args, **_kwargs: {
        "intents": [
                {"intent": "stock_recommendation", "query": "推荐两只银行股", "confidence": 0.95, "reason": "推荐", "execution_mode": "candidate_search", "requires_slot_extraction": False},
                {"intent": "asset_allocation", "query": "将10万元配置到推荐股票", "confidence": 0.94, "reason": "配置", "execution_mode": "allocation", "requires_slot_extraction": True},
                {"intent": "casual_chat", "query": "回应投资焦虑", "confidence": 0.9, "reason": "情绪", "execution_mode": "conversation", "requires_slot_extraction": False},
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
    system.finance_slots_extractor.extract_slots = lambda *_args, **_kwargs: {
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
            "execution_mode": "allocation", "requires_slot_extraction": True,
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

    system.finance_slots_extractor.extract_slots = extract_slots

    result = system.graph.invoke(
        make_state(query, "malformed-tool-calls"),
        config={"configurable": {"thread_id": "malformed-tool-calls"}},
    )

    assert result["slot_tool_source"] == "deterministic_fallback"
    assert result["slot_tool_called"] is True
    assert calls == [query]


@pytest.mark.parametrize("bad_result", [
    None,
    {
        "user_profile": {},
        "resolved_stocks": [None],
        "explicit_stock_codes": [],
    },
])
def test_malformed_tool_result_does_not_block_other_intents(monkeypatch, bad_result):
    system = AdvisorSystem()
    market_query = "分析600519基本面"
    allocation_query = "用10万元做稳健配置"
    system.supervisor.plan_tasks = lambda *_args, **_kwargs: {
        "intents": [
            {
                    "intent": "market_query", "query": market_query,
                    "confidence": 0.95, "reason": "基本面",
                    "execution_mode": "security_analysis",
                    "requires_slot_extraction": True,
            },
            {
                    "intent": "asset_allocation", "query": allocation_query,
                    "confidence": 0.95, "reason": "配置",
                    "execution_mode": "allocation",
                    "requires_slot_extraction": True,
            },
        ],
        "finance_related": True,
        "intent_source": "model",
        "task_plan": [
            "data_fetch", "fundamental_analysis", "asset_allocation", "compliance",
        ],
    }
    system.supervisor.decide_slot_tool_calls = lambda *_args, **_kwargs: [
        {
            "name": "extract_finance_slots",
            "args": {"intent": "market_query", "query": market_query},
            "id": "market-call",
        },
        {
            "name": "extract_finance_slots",
            "args": {"intent": "asset_allocation", "query": allocation_query},
            "id": "allocation-call",
        },
    ]

    class FakeSlotTool:
        def invoke(self, args):
            if args["intent"] == "market_query":
                return bad_result
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

    monkeypatch.setattr(
        orchestrator_module,
        "create_extract_finance_slots_tool",
        lambda *_args, **_kwargs: FakeSlotTool(),
    )

    thread_id = "bad-tool-result-none" if bad_result is None else "bad-tool-result-stock"
    result = system.graph.invoke(
        make_state("分析600519基本面，并用10万元稳健配置", thread_id),
        config={"configurable": {"thread_id": thread_id}},
    )

    assert result["user_profile"]["budget_amount"] == 100000
    assert "market_query" in result["slot_tool_error"]
    assert result["slot_tool_called"] is True
