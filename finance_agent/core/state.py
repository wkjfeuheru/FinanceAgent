"""金融投顾系统核心 State 定义。

精简后的 AdvisorState（~20 字段，从原来的 35+ 精简而来）。
"""

from __future__ import annotations

from typing import Any, Dict, List

from typing_extensions import TypedDict


class AdvisorState(TypedDict, total=False):
    """金融投顾多 Agent 系统的共享状态。

    精简原则：
    - 保留多节点共享的关键字段
    - 移除单节点内部使用的临时字段（slot_tool_*、stock_*_entries 等）
    - 移除改为 Agent 内部状态管理的字段（intent_clarification_*、business_state 等）
    """

    # ── 输入与用户 ──
    user_message: str
    chat_history: List[Dict[str, str]]
    customer_id: str

    # ── 计划与意图 ──
    task_plan: List[str]
    detected_intents: List[Dict[str, Any]]
    intent_results: Dict[str, Dict[str, Any]]  # 按 intent 组织的结果

    # ── 用户画像与股票 ──
    user_profile: Dict[str, Any]
    resolved_stocks: List[Dict[str, Any]]
    candidate_stocks: List[Dict[str, Any]]
    sector_keywords: List[str]

    # ── 数据与分析 ──
    stock_data: Dict[str, Any]          # 每只股票的数据
    stock_analysis: Dict[str, Any]      # 综合分析结果
    allocation_result: Dict[str, Any]   # MPT 配置结果
    compliance_result: Dict[str, Any]   # 合规审查结果

    # ── 输出 ──
    agent_response: str

    # ── 运行时 ──
    memory_context: str
    intent_context: str
    shared_memory_snapshot: Dict[str, Any]
    thread_id: str
    run_id: str
