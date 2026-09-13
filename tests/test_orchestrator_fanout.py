"""股票任务纳入 DAG 调度：并行取数、逐只结论、批次内并行与预算覆盖。

重构前股票路径是 Send 旁路扇出，绕过 ``run_task_dag``（无重试/超时/依赖语义），
且同一请求里的第二个股票任务会走另一条路径。现在所有任务统一由 DAG 调度，
并行取数下沉到专家内部。
"""

from __future__ import annotations

import threading

from langgraph.checkpoint.memory import MemorySaver

from finance_agent.agents.supervisor import ManagerAgent
from finance_agent.orchestrator import orchestrator as orchestrator_module
from finance_agent.orchestrator.orchestrator import AdvisorSystem
from finance_agent.orchestrator.scheduler import ExpertResult, TaskContext, run_task_dag
from finance_agent.contracts import ExpertStatus, Task
from finance_agent.orchestrator.state import dedupe_concat, merge_dict


def _make_system(*, stock_agent, classifier_intents, monkeypatch, fetch):
    system = object.__new__(AdvisorSystem)
    system.checkpointer = MemorySaver()
    system.manager = ManagerAgent()
    system.manager._intent_classifier = type(
        "C", (), {"classify": lambda self, *a, **k: {
            "finance_related": True, "intents": classifier_intents,
        }},
    )()
    system.stock_agent = stock_agent
    system.market_insight_agent = type("M", (), {"invoke": lambda self, s: s})()
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
    monkeypatch.setattr(
        orchestrator_module, "fetch_stock_data", fetch,
    )
    return system


def _stock_agent(*, codes, seen):
    """真实专家替身：与生产同形——先并行取数，再逐只出结论。"""
    from finance_agent.agents.stock_analysis import StockAnalysisAgent
    from finance_agent.research.contracts import AnalysisKind, AnalysisRequest

    class FakeStock(StockAnalysisAgent):
        def __init__(self):
            pass

        def _fetch_stock_data_parallel(self, codes_arg, state):
            seen.append(sorted(codes_arg))
            return {code: {"basic_info": {"code": code}} for code in codes_arg}

        def invoke(self, state):
            kind = AnalysisKind.SINGLE_STOCK if len(codes) == 1 else AnalysisKind.COMPARISON
            request = AnalysisRequest(kind=kind, stock_codes=list(codes))
            return self.run_resolved(state, request)

        def run_resolved(self, state, request):
            # 与生产一致：先取数（记录并行批次的代码集合），再出结论。
            state["stock_data"] = self._fetch_stock_data_parallel(list(request.stock_codes), state)
            state["intent_results"] = {
                "stock_recommendation": {"status": "success", "content": "推荐完成"},
            }
            state["agent_response"] = "推荐完成"
            state["stock_analysis"] = {code: {"code": code} for code in request.stock_codes}
            state["analysis_results"] = [
                {"request": {"stock_codes": [code]}, "action": "关注"} for code in request.stock_codes
            ]
            return state

    return FakeStock()


def test_multi_candidate_task_goes_through_dag_with_parallel_fetch(monkeypatch):
    """股票任务由 DAG 调度，批次内并行取数，逐只结论且 task_results 完整。"""
    seen: list[list[str]] = []
    fetched: list[str] = []

    def fetch(codes):
        fetched.extend(codes)
        return {code: {"basic_info": {"code": code}} for code in codes}

    system = _make_system(
        stock_agent=_stock_agent(codes=["600519", "600036", "000858"], seen=seen),
        classifier_intents=[{
            "intent": "stock_recommendation", "query": "推荐几只消费龙头",
            "confidence": 0.99, "execution_mode": "candidate_search", "evidence": "推荐几只消费龙头",
        }],
        monkeypatch=monkeypatch, fetch=fetch,
    )
    result = system._build_graph().invoke(
        {"user_message": "推荐几只消费龙头", "completed_experts": [], "intent_results": {},
         "intent_slots": {}},
        config={"configurable": {"thread_id": "dag-candidates"}},
    )

    assert seen == [["000858", "600036", "600519"]]
    assert set(result["task_results"]) == {"task-1"}
    assert result["run_status"].value == "completed"


def test_all_stock_tasks_use_the_same_dag_path(monkeypatch):
    """同一请求里的多个股票任务都必须走 DAG，不存在旁路。"""
    seen: list[list[str]] = []

    def fetch(codes):
        return {code: {"basic_info": {"code": code}} for code in codes}

    system = _make_system(
        stock_agent=_stock_agent(codes=["600519"], seen=seen),
        classifier_intents=[
            {"intent": "stock_analysis", "query": "分析600519", "confidence": 0.99,
             "execution_mode": "stock_analysis", "evidence": "分析600519"},
            {"intent": "stock_recommendation", "query": "推荐几只", "confidence": 0.99,
             "execution_mode": "candidate_search", "evidence": "推荐几只"},
        ],
        monkeypatch=monkeypatch, fetch=fetch,
    )
    result = system._build_graph().invoke(
        {"user_message": "分析600519并推荐几只", "completed_experts": [], "intent_results": {},
         "intent_slots": {}},
        config={"configurable": {"thread_id": "dag-multi"}},
    )

    # 两个任务都执行且都经 DAG；三次取数 = 任务一线的1只 + 任务二的1只（去重前）。
    assert set(result["task_results"]) == {"task-1", "task-2"}
    assert len(seen) >= 1


def test_send_bypass_is_gone():
    """回归护栏：Send 扇出与专用分片状态键不得复活。"""
    import finance_agent.orchestrator.orchestrator as module

    assert not hasattr(module, "Send")
    source = open(module.__file__, encoding="utf-8").read()
    for token in ("plan_tasks", "fetch_security", "aggregate_handler", "planned_branches",
                  "stock_fragment_errors", "stock_plan_error"):
        assert token not in source, f"Send 旁路残留：{token}"

    from finance_agent.orchestrator import state as state_module

    assert not hasattr(state_module.AdvisorState, "__annotations__") or all(
        key not in state_module.AdvisorState.__annotations__
        for key in ("planned_branches", "stock_fragment_errors", "fetch_code")
    )


def test_dag_budget_override_applies_per_expert():
    """按 expert 的预算覆盖：股票任务放宽，其余专家沿用默认。"""
    recorded: list[tuple[str, float, float]] = []

    def fake_execute(task, context, *, max_retries, timeout_seconds, deadline_seconds):
        recorded.append((task.expert_name, timeout_seconds, deadline_seconds))
        return ExpertResult(
            task_id=task.task_id, intent=task.intent, expert_name=task.expert_name,
            status=ExpertStatus.SUCCESS, summary="ok",
        )

    import finance_agent.orchestrator.scheduler as scheduler_module

    original = scheduler_module.execute_task_with_retry
    scheduler_module.execute_task_with_retry = fake_execute
    try:
        tasks = [
            Task(task_id="t1", intent="stock_analysis", expert_name="stock_analysis", requirement="x"),
            Task(task_id="t2", intent="casual_chat", expert_name="casual_chat", requirement="y"),
        ]
        run_task_dag(
            tasks, TaskContext(runner=lambda *a: None),
            max_retries=2, timeout_seconds=90, deadline_seconds=180,
            budgets={"stock_analysis": {"timeout_seconds": 120, "deadline_seconds": 300}},
        )
    finally:
        scheduler_module.execute_task_with_retry = original

    by_expert = {name: (timeout, deadline) for name, timeout, deadline in recorded}
    assert by_expert["stock_analysis"] == (120, 300)
    assert by_expert["casual_chat"] == (90, 180)


def test_reducers_merge_dicts_and_dedupe_lists():
    """最小 reducer：映射按 key 合并，列表按身份去重。"""
    assert merge_dict({"a": {"x": 1}}, {"a": {"y": 2}, "b": 3}) == {"a": {"x": 1, "y": 2}, "b": 3}
    assert dedupe_concat([{"fact_id": "f1"}, {"fact_id": "f2"}], [{"fact_id": "f1"}]) == [
        {"fact_id": "f1"}, {"fact_id": "f2"},
    ]


def test_failed_task_local_state_is_not_merged(monkeypatch):
    """超时/失败任务的本地状态不得污染共享状态与 agent_response。

    专家线程在超时后仍可能继续运行并留下迟到写入，因此合并必须按结果状态过滤。
    """
    def fetch(codes):
        return {code: {"basic_info": {"code": code}} for code in codes}

    class RaisingAgent:
        agent_name = "stock_analysis"

        def invoke(self, state):
            raise RuntimeError("boom")

    system = _make_system(
        stock_agent=RaisingAgent(),
        classifier_intents=[{
            "intent": "stock_analysis", "query": "分析600519", "confidence": 0.99,
            "execution_mode": "stock_analysis", "evidence": "分析600519",
        }],
        monkeypatch=monkeypatch, fetch=fetch,
    )
    result = system._build_graph().invoke(
        {"user_message": "分析600519", "completed_experts": [], "intent_results": {},
         "intent_slots": {"stock_analysis": {"stock_codes": ["600519"]}}},
        config={"configurable": {"thread_id": "failed-merge-test"}},
    )

    assert result["task_results"]["task-1"].status.value == "failed"
    # 失败任务不产出专家结果，也不污染共享状态。
    assert not result.get("stock_analysis")
    assert not result.get("stock_data")
