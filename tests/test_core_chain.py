"""核心总管-专家链路回归测试。"""

from langgraph.checkpoint.memory import MemorySaver

from finance_agent.agents.stock_analysis import StockAnalysisAgent
from finance_agent.agents.supervisor import ManagerAgent


def history_fixture(length=40, start=10.0, step=0.2):
    """生成可复现的最小日线数据。"""
    return {
        "data": [
            {
                "date": f"2024-01-{index + 1:02d}",
                "open": start + index * step,
                "high": start + index * step + 0.5,
                "low": start + index * step - 0.5,
                "close": start + index * step,
                "volume": 1000,
            }
            for index in range(length)
        ]
    }


def stock_data_fixture():
    return {
        "600519": {
            "basic_info": {"name": "贵州茅台"},
            "indicators": {"roe": 20, "pe": 25},
            "history": history_fixture(start=100),
        },
        "000001": {
            "basic_info": {"name": "平安银行"},
            "indicators": {"roe": 10, "pe": 8},
            "history": history_fixture(start=12, step=0.05),
        },
    }


class FakeClassifier:
    def __init__(self, payload):
        self.payload = payload

    def classify(self, *args, **kwargs):
        return self.payload


def test_manager_dispatch_preserves_requirement(monkeypatch):
    """总管只抽取需求并映射专家，不加工成子任务。"""
    manager = ManagerAgent()
    manager._intent_classifier = FakeClassifier({
        "finance_related": True,
        "intents": [{
            "intent": "product_analysis",
            "query": "帮我解读一下易方达蓝筹精选",
            "confidence": 0.95,
            "execution_mode": "product_analysis",
            "evidence": "帮我解读一下易方达蓝筹精选",
        }],
    })
    state = {"user_message": "帮我解读一下易方达蓝筹精选"}

    dispatch = manager.dispatch_tasks(state)

    assert dispatch == [{
        "intent": "product_analysis",
        "expert": "product_analysis",
        "requirement": "帮我解读一下易方达蓝筹精选",
        "execution_mode": "product_analysis",
    }]
    assert state["task_plan"] == ["product_analysis"]


def test_stock_agent_successful_result_keeps_quote_and_candidate(monkeypatch):
    """股票专家确定性结果必须能写回完整股票条目。"""
    agent = StockAnalysisAgent()
    data = stock_data_fixture()
    data["600519"]["quote"] = {"price": 1700}
    data["600519"]["search_candidate"] = {"source": "fixture"}

    result = agent.handle_single_stock(
        "600519", "请分析600519", stock_data=data,
    )

    assert result["code"] == "600519"
    assert result["quote"] == {"price": 1700}
    assert result["search_candidate"] == {"source": "fixture"}


def test_langgraph_routes_expert_result_into_manager_synthesis(monkeypatch):
    """主图应按总管分派、专家执行、总管合成的顺序完成一轮请求。"""
    from finance_agent.orchestrator.orchestrator import AdvisorSystem

    events = []
    system = object.__new__(AdvisorSystem)
    system.checkpointer = MemorySaver()
    system.manager = ManagerAgent()
    system.stock_agent = object()
    system.product_agent = object()
    class FakeCasualAgent:
        def invoke(self, state):
            return {
                **state,
                "intent_results": {
                    "casual_chat": {
                        "status": "success",
                        "content": "你好，我是投顾助手。",
                    }
                },
            }

    system.casual_chat_agent = FakeCasualAgent()
    class FakeSlotExtractor:
        def extract(self, state):
            return state
    system.slot_extractor = FakeSlotExtractor()
    system._progress_context = type("Context", (), {})()
    system._progress_callbacks = {}
    system._progress_lock = __import__("threading").Lock()
    system._trace_lock = __import__("threading").Lock()
    system._trace_sequences = {}
    system._workflow_lock = __import__("threading").RLock()
    system._stop_requests = {}
    system._active_runs = {}
    system._stop_lock = __import__("threading").Lock()
    system.audit = type("_NoopAudit", (), {"is_available": lambda self: False})()
    system._trace_agent = lambda state, name: events.append(name)
    system._emit_progress = lambda *args, **kwargs: None

    def fake_dispatch(state):
        """真正写入 tasks：新图由 task_batch 统一调度，不再有旧式逐专家回退。"""
        from finance_agent.contracts.adapters import dispatch_plan_to_legacy, normalize_dispatch_plan
        plan = normalize_dispatch_plan(
            [{"intent": "casual_chat", "query": "你好", "confidence": 0.99,
              "execution_mode": "conversation", "evidence": "你好"}],
            "你好",
        )
        state["tasks"] = plan.tasks
        return dispatch_plan_to_legacy(plan)

    monkeypatch.setattr(system.manager, "dispatch_tasks", fake_dispatch)
    system.casual_chat_agent.invoke = lambda state: {
        **state,
        "intent_results": {"casual_chat": {"status": "success", "content": "你好，我是投顾助手。"}},
    }
    monkeypatch.setattr(
        system.manager,
        "synthesize_response",
        lambda state: "你好，我是投顾助手。\n\n### 风险提示",
    )

    graph = system._build_graph()
    result = graph.invoke({"user_message": "你好", "completed_experts": [], "intent_results": {}}, config={"configurable": {"thread_id": "chain-test"}})

    assert events == ["ManagerAgent", "SlotExtractor", "casual_chat", "ManagerAgent.synthesis"]
    assert result["agent_response"].startswith("你好")


def test_no_tasks_routes_straight_to_synthesis_without_experts(monkeypatch):
    """无 tasks（未分派）时直接进入合成，不执行任何专家。"""
    from langgraph.checkpoint.memory import MemorySaver
    from finance_agent.orchestrator.orchestrator import AdvisorSystem

    system = object.__new__(AdvisorSystem)
    system.checkpointer = MemorySaver()
    system.manager = ManagerAgent()
    system.stock_agent = object()
    system.product_agent = object()
    system.casual_chat_agent = object()
    system.slot_extractor = type("Slots", (), {"extract": lambda self, state: state})()
    import threading
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
    system._trace_agent = lambda *args, **kwargs: None
    system._emit_progress = lambda *args, **kwargs: None
    monkeypatch.setattr(system.manager, "dispatch_tasks", lambda state: [])
    monkeypatch.setattr(system.manager, "synthesize_response", lambda state: "请补充信息")

    graph = system._build_graph()
    result = graph.invoke(
        {"user_message": "嗯", "completed_experts": [], "intent_results": {}},
        config={"configurable": {"thread_id": "no-task-test"}},
    )

    assert result["agent_response"] == "请补充信息"
    assert not result.get("task_results")


def test_manager_synthesis_combines_expert_outputs():
    manager = ManagerAgent()
    state = {
        "intent_results": {
            "stock_analysis": {"status": "success", "content": "股票分析结果"},
            "market_insight": {"status": "success", "content": "市场洞察结果"},
        }
    }

    response = manager.synthesize_response(state)

    assert "股票分析结果" in response
    assert "市场洞察结果" in response
    assert "风险提示" in response


def test_task_batch_executes_same_expert_for_distinct_intents(monkeypatch):
    from langgraph.checkpoint.memory import MemorySaver
    from finance_agent.contracts import IntentKind, Task
    from finance_agent.orchestrator.orchestrator import AdvisorSystem

    system = object.__new__(AdvisorSystem)
    system.checkpointer = MemorySaver()
    system.manager = ManagerAgent()
    system.manager._intent_classifier = FakeClassifier({
        "finance_related": True,
        "intents": [
            {"intent": "stock_analysis", "query": "分析600519", "confidence": 0.99,
             "execution_mode": "stock_analysis", "evidence": "分析600519"},
            {"intent": "stock_recommendation", "query": "推荐AI股票", "confidence": 0.99,
             "execution_mode": "candidate_search", "evidence": "推荐AI股票"},
        ],
    })
    calls = []

    class FakeAgent:
        agent_name = "stock_analysis"

        def plan(self, state):
            """两个股票意图都不带代码，走 defer 让 DAG 逐 task 执行。"""
            return {"kind": "defer"}

        def invoke(self, state):
            calls.append(state["current_task_intent"])
            intent = state["current_task_intent"]
            state.setdefault("intent_results", {})[intent] = {
                "status": "success", "content": f"{intent}完成",
            }
            state["stock_analysis"] = {"600519": {"code": "600519"}}
            return state

    class FakeOther:
        def invoke(self, state):
            return state

    system.stock_agent = FakeAgent()
    system.product_agent = FakeOther()
    system.casual_chat_agent = FakeOther()
    system.slot_extractor = type("Slots", (), {"extract": lambda self, state: state})()
    import threading
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
    system._trace_agent = lambda *args, **kwargs: None
    system._emit_progress = lambda *args, **kwargs: None

    graph = system._build_graph()
    result = graph.invoke(
        {"user_message": "分析600519并推荐AI股票", "completed_experts": [], "intent_results": {}},
        config={"configurable": {"thread_id": "task-batch-test"}},
    )

    assert sorted(calls) == ["stock_analysis", "stock_recommendation"]
    assert set(result["task_results"]) == {"task-1", "task-2"}
    assert result["task_results"]["task-1"].intent is IntentKind.STOCK_ANALYSIS
    assert result["task_results"]["task-2"].intent is IntentKind.STOCK_RECOMMENDATION
