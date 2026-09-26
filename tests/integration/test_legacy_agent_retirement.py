"""V2 生产编排与旧编排退役边界。

生产只有一条执行路径（Root Graph）；旧 Supervisor/专家 Agent、旧 DAG 调度器与
``ORCHESTRATION_V2_ENABLED`` 开关都已删除。此处不依赖 PostgreSQL/网络。
"""

from __future__ import annotations

import importlib
import inspect

from finance_agent.application.advisor import AdvisorSystem


def test_legacy_agent_modules_are_deleted():
    for legacy in (
        "finance_agent.agents",
        "finance_agent.agents.supervisor",
        "finance_agent.agents.stock_analysis",
        "finance_agent.agents.market_insight",
        "finance_agent.agents.product_analysis",
        "finance_agent.agents.casual_chat",
        "finance_agent.agents.base",
        "finance_agent.orchestration.scheduler",
        "finance_agent.orchestration.context_builder",
        "finance_agent.orchestration.slots",
    ):
        try:
            importlib.import_module(legacy)
        except ModuleNotFoundError:
            continue
        raise AssertionError(f"遗留模块仍存在：{legacy}")


def test_orchestration_switch_is_removed():
    from finance_agent.infrastructure import settings as config

    assert not hasattr(config, "ORCHESTRATION_V2_ENABLED")
    source = inspect.getsource(AdvisorSystem)
    assert "ORCHESTRATION_V2_ENABLED" not in source
    assert "_handle_message_legacy" not in source
    assert "_build_graph" not in source


def test_handle_message_has_a_single_v2_path(monkeypatch):
    """handle_message 直接走根图，不存在旧路径分支。"""
    system = object.__new__(AdvisorSystem)
    system._workflow_lock = __import__("threading").RLock()
    called = {}

    class _Supervisor:
        def invoke(self, state, config=None):
            called["state"] = state
            # 新契约：每轮派生状态收在 run 单键下，扇出结论走 task_results。
            return {"run": {"final_response": "ok", "run_status": "completed"}, "task_results": {}}

    system.supervisor = _Supervisor()
    system._failed_output = lambda cid: {"response": "failed", "run_status": "failed"}
    system._persist = lambda *a, **k: None
    system._progress_lock = __import__("threading").Lock()
    system._progress_callbacks = {}
    system._progress_context = type("Ctx", (), {"callback": None})()
    system._trace_lock = __import__("threading").Lock()
    system._trace_sequences = {}
    system._stop_lock = __import__("threading").Lock()
    system._stop_requests = {}
    system._active_runs = {}
    system.memory = type("M", (), {
        "window_size": 10,
        "load_context": lambda self, c, conv, fb: {"profile": {}, "context_text": "", "sliding_window": []},
    })()
    system.audit = type("A", (), {"create_run": lambda *a, **k: None})()
    system.get_checkpoint_conversation_messages = lambda *a, **k: []
    system._emit_progress = lambda *a, **k: None
    system._trace_agent = lambda *a, **k: None
    from finance_agent.safety import find_sensitive_word
    assert find_sensitive_word("你好") is None

    output = system.handle_message("你好", conversation_id="c1")

    assert output["response"] == "ok"
    assert called["state"]["user_message"] == "你好"


def test_v2_root_graph_has_mandatory_compliance_exit():
    """所有执行分支都必须汇聚到一个合规节点，且只有合规节点通向终点。"""
    from finance_agent.orchestration.graphs.supervisor import build_supervisor_graph, SupervisorDependencies

    graph = build_supervisor_graph(SupervisorDependencies(classifier=object()))
    nodes = {name for name in graph.get_graph().nodes}
    ends = [edge for edge in graph.get_graph().edges if edge[1] == "__end__"]

    assert "compliance" in nodes
    assert ends, "graph must terminate"
    assert all(edge[0] == "compliance" for edge in ends)
