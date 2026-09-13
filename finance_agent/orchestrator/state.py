"""金融投顾系统核心 State 定义。

AdvisorState 是 LangGraph 跨专家显式传递的唯一状态通道。
所有字段均为可选（total=False），各节点按需读写。

逐标的 Send 扇出会并发写同一批键，因此对**并发写入的键**声明最小 reducer：
- 映射类（分片结果、股票数据、兼容展示字段）按 key 合并；
- 列表类（事实、分析结果、完成记录、告警）拼接并按身份去重。
其余字段保持 LangGraph 默认的 last-write-wins。
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Dict, List

from typing_extensions import TypedDict

from finance_agent.contracts import ExpertResult, FactSnapshot, RunStatus, Task


def _identity(value: Any) -> str:
    """返回去重身份：优先业务 ID，其次稳定 JSON 序列化。"""
    for attr in ("fact_id", "task_id"):
        identifier = getattr(value, attr, None)
        if identifier:
            return str(identifier)
    if isinstance(value, dict):
        for key in ("fact_id", "task_id", "stock_code", "code"):
            if value.get(key):
                return str(value[key])
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(value)


def merge_dict(left: Dict[str, Any] | None, right: Dict[str, Any] | None) -> Dict[str, Any]:
    """并发分支写入的映射按 key 合并；同 key 的嵌套 dict 再浅合并。"""
    merged = dict(left or {})
    for key, value in (right or {}).items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            nested = dict(current)
            nested.update(value)
            merged[key] = nested
        else:
            merged[key] = value
    return merged


def dedupe_concat(left: List[Any] | None, right: List[Any] | None) -> List[Any]:
    """并发分支写入的列表拼接并按身份去重（保持首次出现顺序）。"""
    merged = list(left or [])
    seen = {_identity(item) for item in merged}
    for item in right or []:
        identifier = _identity(item)
        if identifier in seen:
            continue
        seen.add(identifier)
        merged.append(item)
    return merged


class AdvisorState(TypedDict, total=False):
    """金融投顾多 Agent 系统的共享状态。"""

    # ── 输入与用户 ──
    user_message: str
    requirement: str
    chat_history: List[Dict[str, str]]
    customer_id: str

    # ── 计划与意图 ──
    task_plan: List[str]
    task_dispatch: List[Dict[str, Any]]
    tasks: List[Task]
    completed_experts: Annotated[List[str], dedupe_concat]
    detected_intents: List[Dict[str, Any]]
    uncertain_intents: List[Dict[str, Any]]
    intent_results: Annotated[Dict[str, Dict[str, Any]], merge_dict]
    task_results: Dict[str, ExpertResult]
    facts: Annotated[List[FactSnapshot], dedupe_concat]
    # 意图后槽位提取层产出的结构化入参（按意图 key 组织，跨轮合并）
    intent_slots: Dict[str, Dict[str, Any]]
    finance_related: bool
    run_status: RunStatus
    warnings: Annotated[List[str], dedupe_concat]
    business_state: Dict[str, Any]

    # ── 运行级研究请求留档（审计按一次运行归组重放）──
    research_request: Dict[str, Any]

    # ── 用户画像与股票 ──
    user_profile: Dict[str, Any]
    resolved_stocks: List[Dict[str, Any]]
    explicit_user_stock_codes: List[str]

    # ── 数据与分析 ──
    stock_data: Annotated[Dict[str, Any], merge_dict]
    stock_analysis: Annotated[Dict[str, Any], merge_dict]
    technical_analysis: Annotated[Dict[str, Any], merge_dict]
    analysis_results: Annotated[List[Dict[str, Any]], dedupe_concat]
    theme_screening: Dict[str, Any]
    theme_screening_status: str
    theme_candidates: Annotated[List[Dict[str, Any]], dedupe_concat]
    pending_leads: Annotated[List[Dict[str, Any]], dedupe_concat]
    personalization_status: str
    product_analysis: Dict[str, Any]
    market_insight: Dict[str, Any]
    compliance_result: Dict[str, Any]

    # ── 输出 ──
    agent_response: str
    clarification_question: str

    # ── 运行时 ──
    memory_context: str
    thread_id: str
    run_id: str
    trace_id: str
    message_id: str

