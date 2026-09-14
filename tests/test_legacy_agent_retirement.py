"""V2 生产路径与旧编排退役边界。

生产默认启用 V2 根图；旧路径仅在显式关闭开关时使用。此处不依赖 PostgreSQL/网络，
只验证执行路径选择与合规出口存在。
"""

from __future__ import annotations

import threading

from finance_agent import config
from finance_agent.orchestrator.orchestrator import AdvisorSystem


def test_v2_is_the_production_default():
    """生产默认走 V2 根图；旧路径需显式关闭开关。"""
    assert config.ORCHESTRATION_V2_ENABLED is True


def test_handle_message_dispatches_to_v2_when_enabled(monkeypatch):
    system = object.__new__(AdvisorSystem)
    system._orchestration_v2 = True
    called = {}

    def fake_v2(message, **kwargs):
        called["v2"] = message
        return {"response": "v2", "run_status": "completed"}

    monkeypatch.setattr(system, "handle_message_v2", fake_v2)
    result = system.handle_message("你好")

    assert called["v2"] == "你好"
    assert result["response"] == "v2"


def test_handle_message_falls_back_only_when_flag_disabled(monkeypatch):
    system = object.__new__(AdvisorSystem)
    system._orchestration_v2 = False
    called = {}

    def legacy(message, **kwargs):
        called["legacy"] = message
        return {"response": "legacy"}

    monkeypatch.setattr(system, "_handle_message_legacy", legacy)
    result = system.handle_message("你好")

    assert called["legacy"] == "你好"
    assert result["response"] == "legacy"


def test_v2_root_graph_has_mandatory_compliance_exit():
    """所有执行分支都必须汇聚到一个合规节点，且只有合规节点通向终点。"""
    from finance_agent.orchestrator.root_graph import build_root_graph, RootGraphDependencies

    graph = build_root_graph(RootGraphDependencies(classifier=object()))
    nodes = {name for name in graph.get_graph().nodes}
    ends = [edge for edge in graph.get_graph().edges if edge[1] == "__end__"]

    assert "compliance" in nodes
    assert ends, "graph must terminate"
    assert all(edge[0] == "compliance" for edge in ends)
