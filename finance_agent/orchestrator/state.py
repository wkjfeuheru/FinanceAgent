"""金融投顾系统核心 State 定义。

AdvisorState 是 LangGraph 跨专家显式传递的唯一状态通道。
所有字段均为可选（total=False），各节点按需读写。
"""

from __future__ import annotations

from typing import Any, Dict, List

from typing_extensions import TypedDict

from finance_agent.contracts import ExpertResult, FactSnapshot, RunStatus, Task


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
    completed_experts: List[str]
    detected_intents: List[Dict[str, Any]]
    uncertain_intents: List[Dict[str, Any]]
    intent_results: Dict[str, Dict[str, Any]]
    task_results: Dict[str, ExpertResult]
    facts: List[FactSnapshot]
    # 意图后槽位提取层产出的结构化入参（按意图 key 组织，跨轮合并）
    intent_slots: Dict[str, Dict[str, Any]]
    finance_related: bool
    run_status: RunStatus
    warnings: List[str]
    business_state: Dict[str, Any]

    # ── 用户画像与股票 ──
    user_profile: Dict[str, Any]
    resolved_stocks: List[Dict[str, Any]]
    explicit_user_stock_codes: List[str]

    # ── 数据与分析 ──
    stock_data: Dict[str, Any]
    stock_analysis: Dict[str, Any]
    technical_analysis: Dict[str, Any]
    allocation_result: Dict[str, Any]
    debate_result: Dict[str, Any]
    product_analysis: Dict[str, Any]
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
