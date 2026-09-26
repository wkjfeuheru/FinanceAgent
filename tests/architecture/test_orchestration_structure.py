"""Guard the deepened orchestration structure (Task 3).

The orchestration layer must expose cohesive graph modules that own each
graph's state, nodes, edges and projections. ``AdvisorSystem`` must
delegate to bootstrap/recovery/turn collaborators instead of inlining them.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import typing
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
GRAPHS_DIR = REPO_ROOT / "finance_agent" / "orchestration" / "graphs"

#: Graph module → public symbols that must live there (canonical home).
GRAPH_SYMBOLS = {
    "supervisor": (
        "RunState",
        "SupervisorState",
        "SupervisorDependencies",
        "build_supervisor_graph",
        "classify_domains",
        "project_supervisor_state",
        "project_interrupt_state",
        "make_classify_node",
        "make_llm_supervisor_node",
        "make_scope_tasks_node",
        "make_domain_worker",
        "make_converge_node",
        "make_ask_node",
        "make_synthesize_node",
        "task_id_of",
        "run_of",
        "reduce_run_status",
    ),
    "llm_supervisor": (
        "SupervisorAgentState",
        "make_supervisor_node",
        "create_domain_handoff_tool",
    ),
    "conversation": (
        "ConversationState",
        "run_conversation",
        "build_conversation_graph",
        "make_respond_node",
    ),
}

#: 计划层（``graphs/plan_execute.py``）已整体退场：跨领域扇出提升为根图一等公民。
#: 该模块一旦回归，说明有人在根图之外重建了第二条执行路径——这是结构性回退。
RETIRED_GRAPH_MODULES = ("plan_execute",)


def _module_name(path: Path) -> str:
    relative = path.relative_to(REPO_ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def test_graph_package_owns_each_graph() -> None:
    assert GRAPHS_DIR.is_dir(), "finance_agent/orchestration/graphs must exist"
    for name, symbols in GRAPH_SYMBOLS.items():
        module = importlib.import_module(f"finance_agent.orchestration.graphs.{name}")
        missing = [symbol for symbol in symbols if not hasattr(module, symbol)]
        assert missing == [], f"graphs.{name} is missing {missing}"


def test_graph_modules_do_not_depend_on_legacy_node_layer() -> None:
    """Canonical graphs live in orchestration.graphs; the retired nodes split stays gone."""
    offenders: list[str] = []
    for path in sorted(GRAPHS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for imported in _imports(tree):
            if imported == "finance_agent.orchestration.nodes" or imported.startswith(
                "finance_agent.orchestration.nodes."
            ):
                offenders.append(f"{path.relative_to(REPO_ROOT)} imports {imported}")
    assert offenders == [], "Graphs must not use the retired nodes package:\n" + "\n".join(offenders)


def test_graph_symbols_are_owned_by_canonical_modules() -> None:
    """Graph entry points are defined in their cohesive canonical modules."""
    supervisor = importlib.import_module("finance_agent.orchestration.graphs.supervisor")
    conversation = importlib.import_module("finance_agent.orchestration.graphs.conversation")

    assert supervisor.build_supervisor_graph.__module__ == supervisor.__name__
    assert supervisor.SupervisorDependencies.__module__ == supervisor.__name__
    assert supervisor.make_domain_worker.__module__ == supervisor.__name__
    assert conversation.run_conversation.__module__ == conversation.__name__
    assert conversation.make_respond_node.__module__ == conversation.__name__


def test_retired_plan_layer_does_not_come_back() -> None:
    """计划子图退场后不得回归：跨领域扇出只有根图一条路径。"""
    for name in RETIRED_GRAPH_MODULES:
        path = GRAPHS_DIR / f"{name}.py"
        assert not path.exists(), (
            f"graphs/{name}.py 已退场：跨领域扇出必须在根图内完成，"
            "不得再出现第二条执行路径"
        )


def test_cross_domain_fanout_is_expressed_as_send_at_the_root_graph() -> None:
    """跨领域扇出必须以根图 ``Send`` 表达，并注册真实节点。

    旧计划层在 ``plan`` 节点函数里同步 ``invoke`` 了一个未挂 checkpointer 的子图：
    扇出不在图上，检查点覆盖不到，父图的节点级重试还会连带整轮重跑。这里用几个
    可验证的形状约束把它钉住。（领域/会话专家在节点内跑 ``create_agent`` 的 ReAct
    循环是既有且经评审的模式，不在本约束范围内。）

    LLM supervisor 的 ``Send`` 构造在 ``llm_supervisor`` 模块，因此根图与之都需
    出现 ``Send(`` 与 ``domain_worker`` 目标——两条约束共同保证扇出始终在根图上。
    """
    source = (GRAPHS_DIR / "supervisor.py").read_text(encoding="utf-8")
    llm_source = (GRAPHS_DIR / "llm_supervisor.py").read_text(encoding="utf-8")

    assert "Send(" in source or "Send(" in llm_source, "根图必须用 Send 表达跨领域扇出"
    assert '"domain_worker"' in source, "Send 目标必须是根图登记的节点"
    assert 'Send("domain_worker"' in llm_source, "LLM supervisor 的扇出目标必须是 domain_worker"
    assert "build_plan_execute_graph" not in source
    assert "plan_graph" not in source
    assert "deterministic_planner" not in source


#: 允许出现在 ``SupervisorState`` 顶层的键：轮次输入 + 两个已登记通道。
#: 其余每轮派生状态必须放进 ``run``（``classify`` 用 ``Overwrite`` 整键重置），
#: 这样"新增状态键忘了登记清空"在结构上不可能发生——历史上 ``trusted_content``
#: 与 ``param_blocked`` 都曾静默泄漏到下一轮。
_SUPERVISOR_INPUT_KEYS = frozenset({
    "user_message",
    "history",
    "customer_id",
    "conversation_id",
    "thread_id",
    "run_id",
    "user_profile",
})
_SUPERVISOR_CHANNEL_KEYS = frozenset({"task_results", "run"})

#: ``RunState`` 必须登记的每轮派生键（新增/删除都要显式改这里）。
_RUN_STATE_KEYS = frozenset({
    "routing",
    "warnings",
    "degradations",
    "final_response",
    "run_status",
    "compliance",
    "expert_tasks",
    "param_missing",
    "param_blocked",
    "param_cancelled",
    "clarify_rounds",
    "rerun_answers",
    "trusted_sources",
    "trusted_content",
    "deadline_monotonic",
    "halted",
})


def test_supervisor_state_registers_every_top_level_key_explicitly() -> None:
    """顶层状态键只能来自"轮次输入"或两个已登记通道。

    新增一个顶层键会让本测试失败：作者必须显式决定它属于哪一类（绝大多数情况下
    答案是"放进 ``run``"）。跨轮隔离的行为回归见
    ``tests/integration/test_root_fanout_graph.py::test_run_scoped_state_does_not_leak_across_turns``。
    """
    supervisor = importlib.import_module("finance_agent.orchestration.graphs.supervisor")
    hints = typing.get_type_hints(supervisor.SupervisorState, include_extras=True)

    assert set(hints) == set(_SUPERVISOR_INPUT_KEYS | _SUPERVISOR_CHANNEL_KEYS)


def test_run_state_keeps_the_registered_run_scoped_keys() -> None:
    """每轮派生状态集中在一个键里，键集必须与登记表一致。"""
    supervisor = importlib.import_module("finance_agent.orchestration.graphs.supervisor")
    hints = typing.get_type_hints(supervisor.RunState, include_extras=True)

    assert set(hints) == set(_RUN_STATE_KEYS)


def test_advisor_system_delegates_to_collaborators() -> None:
    bootstrap = importlib.import_module("finance_agent.bootstrap")
    recovery = importlib.import_module("finance_agent.application.async_recovery")
    persistence = importlib.import_module("finance_agent.application.run_persistence")
    turn = importlib.import_module("finance_agent.application.turn_coordinator")
    facade = importlib.import_module("finance_agent.application.advisor")

    assert hasattr(bootstrap, "AdvisorDependencies")
    assert hasattr(recovery, "QuantRecovery")
    assert persistence.PersistenceCoordinator.persist.__module__ == persistence.__name__
    assert turn.TurnCoordinator.handle_message.__module__ == turn.__name__

    source = inspect.getsource(facade)
    assert "AdvisorDependencies" in source, "AdvisorSystem must build via the container"
    assert "QuantRecovery" in source, "AdvisorSystem must delegate async recovery"
    assert "PersistenceCoordinator" in source, "AdvisorSystem must delegate persistence"
    assert "TurnCoordinator" in source, "AdvisorSystem must delegate turn execution"
    # The facade keeps its public surface; the collaborators own the heavy bodies.
    assert hasattr(facade.AdvisorSystem, "resolve_run_status")
    assert hasattr(facade.AdvisorSystem, "handle_message")
    assert hasattr(facade.AdvisorSystem, "handle_message_stream")


def test_experts_package_does_not_host_business_adapters() -> None:
    experts = REPO_ROOT / "finance_agent" / "orchestration" / "experts"
    leftover = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in experts.rglob("*.py")
        if path.name not in {"base.py", "registry.py", "__init__.py"}
    ]
    assert leftover == [], "business expert modules must live in domains/*/expert/:\n" + "\n".join(leftover)
