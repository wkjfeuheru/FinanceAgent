"""领域 ReAct 子图的共享机制（设计 §6.4）。

每个领域子图拥有私有 State、领域工具白名单和受限步数，只向根图投影统一的
``DomainOutcome``。v1 的“选择工具”步骤由确定性的 goal→mode 解析完成；领域
工具本身始终是确定性 pipeline。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from finance_agent.orchestrator.contracts import ArtifactRef, BusinessDomain, DomainOutcome, DomainTaskContext


@dataclass
class OperationResult:
    """领域工具执行结果；由子图统一包装为 DomainOutcome。"""

    structured_data: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    limitations: list[str] = field(default_factory=list)
    status: str = "success"
    evidence: list[ArtifactRef] = field(default_factory=list)


@dataclass(frozen=True)
class DomainOperation:
    """一个领域工具：名称、可用模式与确定性处理器。"""

    name: str
    modes: frozenset[str]
    handler: Callable[[DomainTaskContext], OperationResult]


class DomainState(TypedDict, total=False):
    context: DomainTaskContext
    mode: str
    tool_trace: list[str]
    domain_outcome: DomainOutcome


ModeResolver = Callable[[DomainTaskContext], str]


def _context_text(context: DomainTaskContext) -> str:
    return f"{context.task.goal} {context.task.instruction}".lower()


def build_domain_graph(
    domain: BusinessDomain,
    operations: Iterable[DomainOperation],
    *,
    default_mode: str,
    mode_resolver: ModeResolver | None = None,
):
    """编译一个领域子图。

    工具白名单由 ``operations`` 决定：只有注册的模式才能被选中，未注册模式
    返回安全失败，不静默降级到其它领域工具。
    """
    ops = list(operations)
    by_mode: dict[str, DomainOperation] = {}
    for operation in ops:
        for mode in operation.modes:
            by_mode.setdefault(mode, operation)

    def resolve(context: DomainTaskContext) -> str:
        return mode_resolver(context) if mode_resolver else default_mode

    def select_node(state: DomainState) -> dict[str, Any]:
        context = state["context"]
        return {"mode": resolve(context)}

    def execute_node(state: DomainState) -> dict[str, Any]:
        context = state["context"]
        task = context.task
        mode = str(state.get("mode", default_mode))
        operation = by_mode.get(mode)
        if operation is None:
            return {
                "tool_trace": [],
                "domain_outcome": DomainOutcome(
                    task_id=task.task_id,
                    domain=domain,
                    status="failed",
                    summary="",
                    limitations=[f"unsupported_mode:{mode}"],
                ),
            }

        try:
            result = operation.handler(context)
        except Exception:
            return {
                "tool_trace": [operation.name],
                "domain_outcome": DomainOutcome(
                    task_id=task.task_id,
                    domain=domain,
                    status="failed",
                    summary="",
                    limitations=[f"tool_failed:{operation.name}"],
                ),
            }

        structured = dict(result.structured_data)
        structured.setdefault("mode", mode)
        return {
            "tool_trace": [operation.name],
            "domain_outcome": DomainOutcome(
                task_id=task.task_id,
                domain=domain,
                status=result.status,
                summary=result.summary,
                structured_data=structured,
                evidence=result.evidence,
                limitations=result.limitations,
            ),
        }

    graph = StateGraph(DomainState)
    graph.add_node("select", select_node)
    graph.add_node("execute", execute_node)
    graph.add_edge(START, "select")
    graph.add_edge("select", "execute")
    graph.add_edge("execute", END)
    return graph.compile()


def context_text(context: DomainTaskContext) -> str:
    return _context_text(context)


def keyword_mode(text: str, table: Mapping[str, tuple[str, ...]], default: str) -> str:
    """按关键词命中顺序确定模式；无命中返回默认模式。"""
    lowered = text.lower()
    for mode, keywords in table.items():
        if any(keyword in lowered for keyword in keywords):
            return mode
    return default
