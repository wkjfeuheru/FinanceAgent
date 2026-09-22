"""领域 ReAct 子图的共享机制（设计 §6.4）。

每个领域子图拥有私有 State、领域工具白名单和受限步数，只向根图投影统一的
``DomainOutcome``。v1 的“选择工具”步骤由确定性的 goal→mode 解析完成；领域
工具本身始终是确定性 pipeline。节点函数定义在 ``orchestrator.nodes.domain``，
本模块只负责构建操作白名单并装配 select → execute 图。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from finance_agent.contracts import FactSnapshot
from finance_agent.orchestrator.contracts import (
    ArtifactRef,
    AsyncJobRef,
    BusinessDomain,
    DomainOutcome,
    DomainTaskContext,
)
from finance_agent.orchestrator.nodes.domain import make_execute_node, make_select_node

logger = logging.getLogger(__name__)


@dataclass
class OperationResult:
    """领域工具执行结果；由子图统一包装为 DomainOutcome。"""

    structured_data: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    limitations: list[str] = field(default_factory=list)
    status: str = "success"
    evidence: list[ArtifactRef] = field(default_factory=list)
    # 经 QuantGateway 提交、尚未完成的异步任务；processing 结论据此写入
    # DomainOutcome.pending_jobs，供状态端点按 job_id 查询与恢复。
    pending_jobs: list[AsyncJobRef] = field(default_factory=list)


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

    select_node = make_select_node(default_mode, mode_resolver)
    execute_node = make_execute_node(domain, by_mode, default_mode=default_mode)

    graph = StateGraph(DomainState)
    graph.add_node("select", select_node)
    graph.add_node("execute", execute_node)
    graph.add_edge(START, "select")
    graph.add_edge("select", "execute")
    graph.add_edge("execute", END)
    return graph.compile()


def context_text(context: DomainTaskContext) -> str:
    return _context_text(context)


def merge_facts(
    existing: Iterable[FactSnapshot], incoming: Iterable[FactSnapshot],
) -> list[FactSnapshot]:
    """把 ``incoming`` 事实按 ``fact_id`` 去重合并进 ``existing``。

    统一的领域事实合并语义（此前 stock/product 各自复制了一份）：
    保留既有顺序，新增项按传入顺序追加在后；与既有或本轮已加入的事实
    ``fact_id`` 相同的项一律跳过，同一事实不得重复引用。
    """
    merged = list(existing)
    seen = {fact.fact_id for fact in merged}
    for fact in incoming:
        if fact.fact_id in seen:
            continue
        seen.add(fact.fact_id)
        merged.append(fact)
    return merged


def keyword_mode(text: str, table: Mapping[str, tuple[str, ...]], default: str) -> str:
    """按关键词命中顺序确定模式；无命中返回默认模式。"""
    lowered = text.lower()
    for mode, keywords in table.items():
        if any(keyword in lowered for keyword in keywords):
            return mode
    return default
