"""按任务生成最小上下文投影，避免完整 AdvisorState 扩散到模型调用。"""

from __future__ import annotations

from typing import Any

from finance_agent.contracts import ExpertResult, FactSnapshot, Task


# 证据里只给审计使用的重型字段：完整 K 线与原始取数输入不进模型上下文。
AUDIT_ONLY_PAYLOAD_KEYS = frozenset({"inputs", "snapshot"})


def _fact_dict(fact: FactSnapshot | dict[str, Any]) -> dict[str, Any]:
    """投影事实快照，剥离仅供审计重放的重型字段。"""
    data = fact.model_dump(mode="json") if isinstance(fact, FactSnapshot) else dict(fact)
    payload = data.get("payload")
    if isinstance(payload, dict):
        data["payload"] = {
            key: value for key, value in payload.items() if key not in AUDIT_ONLY_PAYLOAD_KEYS
        }
    return data


def _facts_for_task(state: dict[str, Any], task: Task) -> list[dict[str, Any]]:
    facts = [_fact_dict(item) for item in state.get("facts", []) or []]
    domains = {
        "market_insight": {"market"},
        "stock_analysis": {"market", "fundamental", "technical"},
        "stock_recommendation": {"market", "fundamental", "technical"},
        "product_analysis": {"product"},
        "casual_chat": set(),
    }
    allowed = domains.get(task.intent.value if task.intent else "", set())
    # allowed 为空集表示该意图不消费任何事实（如闲聊）；此处必须显式区分，
    # 不能用 `not allowed` 放行全部，否则闲聊会收到所有领域的证据。
    return [fact for fact in facts if fact.get("domain") in allowed]


def build_intent_context(state: dict[str, Any]) -> dict[str, Any]:
    """分类器只接收当前消息与短摘要。"""
    return {
        "current_message": str(state.get("user_message", "")),
        "recent_summary": str(state.get("memory_context", ""))[:1500],
    }


def build_task_context(
    state: dict[str, Any],
    task: Task,
    *,
    max_chars: int = 12000,
) -> dict[str, Any]:
    """生成专家所需的结构化最小上下文。"""
    slots = dict((state.get("intent_slots", {}) or {}).get(
        task.intent.value if task.intent else "", {},
    ) or {})
    facts = _facts_for_task(state, task)
    context = {
        "task_id": task.task_id,
        "intent": task.intent.value if task.intent else "",
        "expert_name": task.expert_name,
        "requirement": task.requirement,
        "execution_mode": task.execution_mode,
        "user_message": str(state.get("user_message", "")),
        "user_profile": dict(state.get("user_profile", {}) or {}),
        "slots": slots,
        "facts": facts,
        "fact_ids": [fact.get("fact_id") for fact in facts if fact.get("fact_id")],
    }
    text = str(context)
    if len(text) > max_chars:
        context["facts"] = facts[: max(1, max_chars // 1000)]
        context["fact_ids"] = [fact.get("fact_id") for fact in context["facts"] if fact.get("fact_id")]
        context["user_profile"] = {
            key: context["user_profile"][key]
            for key in ("risk_preference", "budget_amount", "holding_period", "stock_codes")
            if key in context["user_profile"]
        }
    return context


def build_synthesis_context(
    state: dict[str, Any],
    tasks: list[Task],
    results: list[ExpertResult | dict[str, Any]],
    *,
    max_chars: int = 16000,
) -> dict[str, Any]:
    """只向合成器提供任务摘要、结构化结果和警告。"""
    task_data = [task.model_dump(mode="json") for task in tasks]
    result_data = [
        item.model_dump(mode="json") if isinstance(item, ExpertResult) else dict(item)
        for item in results
    ]
    context = {
        "current_message": str(state.get("user_message", "")),
        "tasks": task_data,
        "results": result_data,
        "warnings": list(state.get("warnings", []) or []),
    }
    if len(str(context)) > max_chars:
        context["results"] = [
            {
                key: result.get(key)
                for key in ("task_id", "intent", "expert_name", "status", "summary", "fact_ids", "error_code")
                if key in result
            }
            for result in result_data
        ]
    return context


__all__ = ["build_intent_context", "build_synthesis_context", "build_task_context"]
