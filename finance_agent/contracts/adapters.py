"""新任务/结果契约与旧字典接口之间的兼容适配。"""

from __future__ import annotations

from typing import Any

from finance_agent.contracts.schema.enums import IntentKind, TaskKind
from finance_agent.contracts.schema.models import DispatchPlan, Task


_EXPERT_BY_INTENT = {
    IntentKind.MARKET_QUERY: "stock_analysis",
    IntentKind.STOCK_RECOMMENDATION: "stock_analysis",
    IntentKind.ASSET_ALLOCATION: "asset_allocation",
    IntentKind.PRODUCT_ANALYSIS: "product_analysis",
    IntentKind.CASUAL_CHAT: "casual_chat",
}


def normalize_dispatch_plan(
    raw_intents: list[dict[str, Any]],
    message: str,
) -> DispatchPlan:
    """将分类器意图规范化为独立、可追踪的任务。"""
    tasks: list[Task] = []
    for raw in raw_intents:
        if not isinstance(raw, dict):
            continue
        try:
            intent = IntentKind(str(raw.get("intent", "")).strip())
        except ValueError:
            continue
        try:
            confidence = float(raw.get("confidence", 0))
        except (TypeError, ValueError):
            continue
        if confidence < 0.9:
            continue
        expert = _EXPERT_BY_INTENT[intent]
        tasks.append(Task(
            task_id=f"task-{len(tasks) + 1}",
            kind=TaskKind(expert),
            intent=intent,
            expert_name=expert,
            requirement=str(raw.get("query", "")).strip() or message.strip(),
            execution_mode=str(raw.get("execution_mode", "")).strip(),
        ))
    stock_tasks = [
        task.task_id for task in tasks
        if task.intent in {IntentKind.MARKET_QUERY, IntentKind.STOCK_RECOMMENDATION}
    ]
    for task in tasks:
        if task.intent is IntentKind.ASSET_ALLOCATION and stock_tasks:
            task.depends_on = list(stock_tasks)
    return DispatchPlan(tasks=tasks)


def dispatch_plan_to_legacy(plan: DispatchPlan) -> list[dict[str, Any]]:
    """将新契约投影成现有 LangGraph/API 使用的 task_dispatch。"""
    return [
        {
            "intent": task.intent.value if task.intent else "",
            "expert": task.expert_name,
            "requirement": task.requirement,
            "execution_mode": task.execution_mode,
        }
        for task in plan.tasks
    ]


def task_plan_to_legacy(plan: DispatchPlan) -> list[str]:
    """生成旧 API 的专家名计划投影。"""
    return list(dict.fromkeys(task.expert_name for task in plan.tasks))


__all__ = [
    "dispatch_plan_to_legacy",
    "normalize_dispatch_plan",
    "task_plan_to_legacy",
]
