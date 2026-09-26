"""任务描述的改写、实体校验与回退（Plan-and-Execute 与单领域共用）。

Supervisor 负责把用户的**本轮原话**（结合近期历史做指代消解）改写为每个领域
一条**自包含**任务描述，再下发给对应专家。专家不接收对话历史——history 只在
规划/改写这一层使用，因此这一层必须保证描述自身携带全部必要信息。

``validate_rewrite`` 是**确定性**防线（不额外调用模型）：从本轮原话抽取关键实体
（6 位代码、被引号/书名号括起的名称、数字+单位过滤条件），要求它们出现在改写后的
描述里；不通过则回退用分类器切出的子请求原文（``domain_queries``），并记 warning。
指代性追问（本轮无实体）不拦截——那种情况本来就该由改写用历史补全。
"""

from __future__ import annotations

import re
from typing import Any

from finance_agent.orchestration.contracts import BusinessDomain, PlanTask
from finance_agent.orchestration.runtime.state import routing_of

#: 6 位数字代码（A 股/产品通吃）。
_SIX_DIGIT_RE = re.compile(r"(?<!\d)\d{6}(?!\d)")
#: 被引号/书名号/中括号括起的名称（"华夏成长基金"、《...》、【...】）。
_QUOTED_RE = re.compile(r"[“\"'《【\[]([^”\"'》】\]]{2,20})[”\"'》】\]]")
#: 数字 + 常见单位/字段的过滤条件（"市盈率低于20" "营收增长20%" "回撤不超过15%"）。
_FILTER_RE = re.compile(
    r"[^，。；\s]{0,12}?(\d+(?:\.\d+)?\s*(?:%|％|倍|亿|万|元|年|天|个月))"
)


def extract_entities(message: str) -> list[str]:
    """抽取本轮原话里的关键实体（去重保序）。空列表表示这是指代性追问。"""
    text = str(message or "")
    entities: list[str] = []

    def _add(value: str) -> None:
        value = value.strip()
        if value and value not in entities:
            entities.append(value)

    for match in _SIX_DIGIT_RE.findall(text):
        _add(match)
    for match in _QUOTED_RE.findall(text):
        _add(match)
    for match in _FILTER_RE.findall(text):
        _add(match)
    return entities


def validate_rewrite(rewrite: str, message: str) -> tuple[bool, list[str]]:
    """校验改写描述是否保留了原话实体；返回 ``(是否通过, 丢失的实体)``。

    本轮没有实体（指代性追问）时一律通过：此时改写本就该用历史补全指代。
    """
    entities = extract_entities(message)
    if not entities:
        return True, []
    text = str(rewrite or "")
    missing = [entity for entity in entities if entity not in text]
    return (not missing), missing


def resolve_description(
    *,
    domain: BusinessDomain,
    message: str,
    rewritten: str,
    fallback: str,
) -> tuple[str, list[str]]:
    """确定该领域的最终任务描述，并在改写丢实体时回退原文。

    ``fallback`` 是分类器切出的领域子请求原文（``routing.domain_queries``）。
    改写通过实体校验则采用改写；否则回退 ``fallback``（无则用整句原话）并返回
    warning 供上层登记。
    """
    candidate = str(rewritten or "").strip()
    if candidate:
        passed, missing = validate_rewrite(candidate, message)
        if passed:
            return candidate, []
        fallback_text = str(fallback or "").strip() or str(message or "").strip()
        return fallback_text, [
            f"task_rewrite_dropped_entities:{domain.value}:" + ",".join(missing)
        ]
    fallback_text = str(fallback or "").strip() or str(message or "").strip()
    return fallback_text, []


def task_from_payload(payload: dict[str, Any], domain: BusinessDomain) -> PlanTask:
    """由持久化的任务载荷重建 ``PlanTask``（缺参重跑用）。"""
    return PlanTask(
        task_id=str(payload.get("task_id") or f"task:{domain.value}"),
        domain=domain,
        goal=str(payload.get("goal") or ""),
        instruction=str(payload.get("instruction") or ""),
        expected_output=str(payload.get("expected_output") or "domain_outcome"),
    )


def task_to_payload(task: PlanTask) -> dict[str, Any]:
    """把 ``PlanTask`` 投影为可放进图状态的普通字典。"""
    return {
        "task_id": task.task_id,
        "domain": task.domain.value,
        "goal": task.goal,
        "instruction": task.instruction,
        "expected_output": task.expected_output,
    }


def scoped_queries(state: dict[str, Any], domains: list[BusinessDomain]) -> dict[str, str]:
    """分类器为每个领域切出的子请求（无则回退整句原话）。"""
    queries = routing_of(state).get("domain_queries") or {}
    message = str(state.get("user_message", "") or "")
    out: dict[str, str] = {}
    for domain in domains:
        text = str(queries.get(domain.value) or "").strip()
        out[domain.value] = text or message
    return out


_REWRITE_PROMPT = """你是任务改写器。把用户请求改写为每个业务领域一条**自包含**的任务描述。

## 要求
1. 每条描述必须独立可执行：**把指代补全**（用户说"那它呢""换成低风险的"时，用近期
   上下文把指代还原为具体实体），并保留用户全部限定条件（过滤条件、指定字段、
   时间范围、分析维度）。
2. **不得新增**用户没提的标的、数字或约束，不得回答问题。
3. 每个领域一条描述，用该领域的语言表达（如股票领域要含标的与关注维度）。
4. 只输出 JSON，形如：{{"tasks": {{"stock_research": "…", "market_insight": "…"}}}}

涉及领域：{domains}
近期上下文：{history}
用户当前消息：{message}"""


def build_llm_rewriter(model: Any, *, fallback: bool = True):
    """把 chat model 适配为任务改写器；解析失败回退确定性子请求。"""
    from finance_agent.infrastructure.llm.factory import build_chat_model_callable

    call = build_chat_model_callable(model, require_json=True)

    def rewrite(state: dict[str, Any], domains: list[BusinessDomain]) -> dict[str, str]:
        base = scoped_queries(state, domains)
        message = str(state.get("user_message", "") or "")
        if not message.strip():
            return base
        prompt = _REWRITE_PROMPT.format(
            domains="、".join(domain.value for domain in domains),
            history=str(state.get("history", "") or "")[:2000] or "（无）",
            message=message,
        )
        try:
            raw = call([{"role": "system", "content": prompt}])
            payload = json.loads(raw) if isinstance(raw, str) else raw
            tasks = payload.get("tasks") if isinstance(payload, dict) else None
        except Exception:  # noqa: BLE001 - 改写失败回退子请求原文
            tasks = None
        if not isinstance(tasks, dict):
            if fallback:
                return base
            raise ValueError("rewrite_failed")

        out: dict[str, str] = {}
        for domain in domains:
            rewritten = str(tasks.get(domain.value) or "").strip()
            description, _ = resolve_description(
                domain=domain, message=message, rewritten=rewritten,
                fallback=base.get(domain.value, ""),
            )
            out[domain.value] = description
        return out

    return rewrite


__all__ = [
    "build_llm_rewriter",
    "extract_entities",
    "resolve_description",
    "scoped_queries",
    "task_from_payload",
    "task_to_payload",
    "validate_rewrite",
]
