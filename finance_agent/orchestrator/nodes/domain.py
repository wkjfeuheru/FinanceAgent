"""领域子图的节点函数（select → execute）。

从 ``domains.base.build_domain_graph`` 的闭包迁出；操作白名单 ``by_mode``
由宿主构建后注入 execute 节点。宿主模块（domains.base）模块级导入本模块
装配节点，因此本模块不得在模块级反向导入宿主——类型引用走 TYPE_CHECKING。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable, Mapping

from finance_agent.orchestrator.contracts import BusinessDomain, DomainOutcome

if TYPE_CHECKING:
    from finance_agent.orchestrator.domains.base import DomainOperation, DomainState

logger = logging.getLogger(__name__)


def make_select_node(
    default_mode: str,
    mode_resolver: Callable[[Any], str] | None,
) -> Callable[["DomainState"], dict[str, Any]]:
    """select 节点工厂：goal→mode 解析（确定性，非 LLM 选工具）。"""

    def select_node(state: "DomainState") -> dict[str, Any]:
        context = state["context"]
        mode = mode_resolver(context) if mode_resolver else default_mode
        return {"mode": mode}

    return select_node


def make_execute_node(
    domain: BusinessDomain,
    by_mode: Mapping[str, "DomainOperation"],
    *,
    default_mode: str,
) -> Callable[["DomainState"], dict[str, Any]]:
    """execute 节点工厂：执行白名单内单个 operation 并包装 DomainOutcome。"""

    def execute_node(state: "DomainState") -> dict[str, Any]:
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
            # 向用户只返回安全失败标识；细节（数据源故障/依赖缺失/代码缺陷）进日志，
            # 否则线上出现 tool_failed 时无法归因。
            logger.exception("domain_operation_failed op=%s", operation.name)
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
                pending_jobs=list(result.pending_jobs),
            ),
        }

    return execute_node


__all__ = ["make_execute_node", "make_select_node"]
