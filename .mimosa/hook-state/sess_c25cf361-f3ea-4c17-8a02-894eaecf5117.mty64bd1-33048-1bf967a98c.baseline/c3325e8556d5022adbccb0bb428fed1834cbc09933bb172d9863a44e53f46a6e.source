"""槽位提取层（Slot Extraction Layer）测试。

覆盖：名称→代码映射、歧义、否定、多轮合并/更新、缺失必填槽位澄清、
以及 search_candidates 的股票名称子串兜底。所有测试均不依赖真实 LLM/MCP。
"""

import json

import pytest

from finance_agent.contracts.adapters import dispatch_plan_to_legacy, normalize_dispatch_plan
from finance_agent.orchestrator import slots
from finance_agent.orchestrator.tools import stockdata


def _dispatch_with_tasks(state, raw_intents):
    """供图级测试：写入真实 tasks（新图由 task_batch 统一调度），并返回旧式分派。"""
    plan = normalize_dispatch_plan(raw_intents, state.get("user_message", ""))
    state["tasks"] = plan.tasks
    return dispatch_plan_to_legacy(plan)

BASICS = [
    {"ts_code": "600519.SH", "name": "贵州茅台", "industry": "白酒"},
    {"ts_code": "000001.SZ", "name": "平安银行", "industry": "银行"},
    {"ts_code": "601318.SH", "name": "中国平安", "industry": "保险"},
    {"ts_code": "000858.SZ", "name": "五粮液", "industry": "白酒"},
]


class FakeSource:
    def get_stock_basic(self, stock_code=""):
        return {"data": [dict(b) for b in BASICS]}

    def get_daily(self, code, start="", end=""):
        return []


class FakeManager:
    """模拟统一 Provider Manager；委托给 FakeSource 避免真实网络调用。"""

    def __init__(self):
        self._source = FakeSource()

    def get_stock_basic(self, stock_code=""):
        return self._source.get_stock_basic(stock_code)

    def get_daily(self, stock_code, start_date="", end_date=""):
        return self._source.get_daily(stock_code, start_date, end_date)


@pytest.fixture
def stock_index(monkeypatch):
    monkeypatch.setattr(slots, "get_provider_manager", lambda: FakeManager())
    slots.reset_stock_index()
    yield
    slots.reset_stock_index()


def _det_extractor(extractor):
    """把 SlotExtractor 的 LLM 抽取替换为确定性抽取，测试无需真实网络。"""
    extractor._extract_one = lambda msg, intent, schema, prior, ctx: slots._deterministic_extract(msg, intent)
    return extractor


def test_resolve_exact_name(stock_index):
    resolved, ambiguous = slots._map_stock_names(["贵州茅台"])
    assert resolved == [{"code": "600519", "name": "贵州茅台"}]
    assert ambiguous == []


def test_resolve_short_name_via_alias(stock_index):
    resolved, ambiguous = slots._map_stock_names(["茅台"])
    assert resolved == [{"code": "600519", "name": "茅台"}]
    assert ambiguous == []


def test_resolve_ambiguous_name_returns_candidates(stock_index):
    resolved, ambiguous = slots._map_stock_names(["平安"])
    assert resolved == []
    assert ambiguous and ambiguous[0]["name"] == "平安"
    assert "000001" in ambiguous[0]["candidates"] and "601318" in ambiguous[0]["candidates"]


def test_deterministic_allocation_extract():
    raw = slots._deterministic_extract("用600519和000001配置10万，稳健，持有1年", "asset_allocation")
    s = raw["slots"]
    assert s["stock_codes"] == ["600519", "000001"]
    assert s["budget_amount"] == 100000
    assert s["risk_preference"] == "R2 中低风险"
    assert s["holding_period"] == "1年"


def test_negation_extracted_as_excluded():
    raw = slots._deterministic_extract("推荐几个AI人工智能股票，不要白酒", "stock_recommendation")
    s = raw["slots"]
    assert "白酒" in s["excluded"]
    # 否定从句不应泄漏进正向主题
    themes = " ".join(s.get("themes", []))
    assert "不要" not in themes


def test_stock_analysis_resolves_name_to_stock_codes(stock_index):
    resolved = slots._resolve_slots(
        "stock_analysis",
        slots._deterministic_extract("我分析一下贵州茅台最近的行情和基本面", "stock_analysis"),
        {},
    )
    assert resolved["stock_codes"] == ["600519"]
    assert resolved["analysis_type"] == "both"
    assert resolved["_required_missing"] is False


def test_stock_analysis_missing_required_flagged(stock_index):
    resolved = slots._resolve_slots(
        "stock_analysis",
        slots._deterministic_extract("分析一下大盘情绪", "stock_analysis"),
        {},
    )
    assert resolved["_required_missing"] is True


def test_extract_populates_resolved_stocks(stock_index):
    extractor = _det_extractor(slots.SlotExtractor())
    state = {
        "user_message": "我分析一下贵州茅台最近的行情和基本面",
        "memory_context": "",
        "task_dispatch": [{
            "intent": "stock_analysis", "expert": "stock_analysis",
            "requirement": "我分析一下贵州茅台最近的行情和基本面",
        }],
        "intent_slots": {},
    }
    out = extractor.extract(state)
    assert out["resolved_stocks"] == [{"code": "600519", "name": "贵州茅台"}]
    assert out["intent_slots"]["stock_analysis"]["stock_codes"] == ["600519"]
    assert out["task_dispatch"]  # 仍派单给 stock_analysis
    assert not out.get("clarification_question")


def test_extract_prunes_and_clarifies_when_required_missing(stock_index):
    extractor = _det_extractor(slots.SlotExtractor())
    state = {
        "user_message": "分析一下市场情绪",
        "memory_context": "",
        "task_dispatch": [{
            "intent": "stock_analysis", "expert": "stock_analysis", "requirement": "分析一下市场情绪",
        }],
        "intent_slots": {},
    }
    out = extractor.extract(state)
    assert out["task_dispatch"] == []  # 已剔除
    assert out["intent_slots"]["stock_analysis"]["_required_missing"] is True
    assert "股票名称" in out["clarification_question"]


def test_extract_ambiguity_raises_clarification(stock_index):
    extractor = slots.SlotExtractor()
    # 模拟 LLM 抽取到短名称"平安"（确定性兜底不会提取短名称）
    extractor._extract_one = lambda msg, intent, schema, prior, ctx: slots._normalize_raw({
        "slots": {"stock_names": ["平安"]}, "negatives": {}, "cleared": [],
        "ambiguity": [], "missing": [],
    })
    state = {
        "user_message": "您提到的平安怎么样",
        "memory_context": "",
        "task_dispatch": [{"intent": "stock_analysis", "expert": "stock_analysis", "requirement": "平安怎么样"}],
        "intent_slots": {},
    }
    out = extractor.extract(state)
    assert "平安" in out["clarification_question"]
    # 歧义不武断选股：resolved_stocks 不包含平安系
    codes = [r["code"] for r in out.get("resolved_stocks", [])]
    assert "601318" not in codes and "000001" not in codes


def test_extract_updates_allocation_profile(stock_index):
    extractor = _det_extractor(slots.SlotExtractor())
    state = {
        "user_message": "用600519配置10万，稳健，持有1年",
        "memory_context": "",
        "user_profile": {"risk_preference": "R3 中风险"},
        "task_dispatch": [{"intent": "asset_allocation", "expert": "asset_allocation", "requirement": "用600519配置10万，稳健，持有1年"}],
        "intent_slots": {},
    }
    out = extractor.extract(state)
    profile = out["user_profile"]
    assert profile["stock_codes"] == ["600519"]
    assert profile["budget_amount"] == 100000
    assert profile["holding_period"] == "1年"
    # 已确认画像字段不被覆盖
    assert profile["risk_preference"] == "R3 中风险"


def test_merge_across_turns_keeps_and_updates_slots(stock_index):
    turn1 = slots._resolve_slots(
        "asset_allocation",
        slots._deterministic_extract("用600519和000001配置", "asset_allocation"),
        {},
    )
    assert set(turn1["stock_codes"]) == {"600519", "000001"}

    # 第二轮只补预算：保留代码并新增预算
    raw2 = slots._normalize_raw({
        "slots": {"budget_amount": 100000}, "negatives": {}, "cleared": [], "ambiguity": [], "missing": [],
    })
    turn2 = slots._resolve_slots("asset_allocation", raw2, turn1)
    assert set(turn2["stock_codes"]) == {"600519", "000001"}
    assert turn2["budget_amount"] == 100000

    # 第三轮清除某字段
    raw3 = slots._normalize_raw({
        "slots": {}, "negatives": {}, "cleared": ["stock_codes"], "ambiguity": [], "missing": [],
    })
    turn3 = slots._resolve_slots("asset_allocation", raw3, turn2)
    assert turn3["stock_codes"] == []


def test_llm_failure_falls_back_to_deterministic(monkeypatch):
    extractor = slots.SlotExtractor()

    def boom(*args, **kwargs):
        raise RuntimeError("io error")

    monkeypatch.setattr(extractor, "_llm_extract", boom)
    out = extractor._extract_one("用600519配置10万，稳健", "asset_allocation", {"slots": []}, {}, "")
    assert out["slots"]["budget_amount"] == 100000


def test_search_candidates_name_substring_match(monkeypatch):
    monkeypatch.setattr(stockdata, "get_provider_manager", lambda: FakeManager())
    raw = stockdata.search_candidates.invoke({
        "user_query": "我分析一下贵州茅台最近的行情和基本面", "max_results": 5,
    })
    result = json.loads(raw)
    assert any(item["code"] == "600519" for item in result)
    assert any("按股票名称匹配" in item["reason"] for item in result)


def test_graph_wires_slots_to_stock_agent(monkeypatch):
    """端到端：总管→槽位层→个股专家，名称"贵州茅台"应映射为 600519 传入专家。"""
    from langgraph.checkpoint.memory import MemorySaver

    from finance_agent.agents.supervisor import ManagerAgent
    from finance_agent.orchestrator.orchestrator import AdvisorSystem

    monkeypatch.setattr(slots, "get_provider_manager", lambda: FakeManager())
    slots.reset_stock_index()

    system = object.__new__(AdvisorSystem)
    system.checkpointer = MemorySaver()
    system.manager = ManagerAgent()
    extractor = slots.SlotExtractor()
    extractor._extract_one = lambda msg, intent, schema, prior, ctx: slots._deterministic_extract(msg, intent)
    system.slot_extractor = extractor

    captured = {}

    class FakeStockAgent:
        def plan(self, state):
            """已解析出具体标的时走 defer，由 DAG 逐 task 交给 invoke。"""
            return {"kind": "defer"}

        def invoke(self, state):
            captured["resolved_stocks"] = state.get("resolved_stocks", [])
            response = "已完成 1 只股票的分析：- 600519 评级：推荐（90分）"
            state["agent_response"] = response
            state.setdefault("intent_results", {})["stock_analysis"] = {
                "status": "success", "content": response,
            }
            state["stock_analysis"] = {
                "600519": {"code": "600519", "rating": "推荐", "overall_score": 90},
            }
            return state

    class FakeOtherAgent:
        def invoke(self, state):
            return state

    system.stock_agent = FakeStockAgent()
    system.allocation_agent = FakeOtherAgent()
    system.product_agent = FakeOtherAgent()
    system.casual_chat_agent = FakeOtherAgent()
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
    system._trace_agent = lambda state, name: None
    system._emit_progress = lambda *a, **k: None
    monkeypatch.setattr(system.manager, "dispatch_tasks", lambda state: _dispatch_with_tasks(
        state, [{
            "intent": "stock_analysis", "query": "我分析一下贵州茅台最近的行情和基本面",
            "confidence": 0.99, "execution_mode": "stock_analysis",
            "evidence": "我分析一下贵州茅台最近的行情和基本面",
        }],
    ))
    monkeypatch.setattr(
        system.manager, "synthesize_response",
        lambda state: state.get("agent_response", "") + "\n\n### 风险提示",
    )

    graph = system._build_graph()
    result = graph.invoke(
        {"user_message": "我分析一下贵州茅台最近的行情和基本面",
         "completed_experts": [], "intent_results": {}, "intent_slots": {}},
        config={"configurable": {"thread_id": "slot-e2e"}},
    )

    assert captured["resolved_stocks"] == [{"code": "600519", "name": "贵州茅台"}]
    assert "未识别到需要分析的股票代码" not in result.get("agent_response", "")
    assert "600519" in result.get("agent_response", "")
