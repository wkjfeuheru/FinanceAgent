"""数据流契约枚举：运行状态、任务类型与专家结果状态。"""

from __future__ import annotations

from enum import Enum


class RunStatus(str, Enum):
    """Agent 运行状态。

    终态（COMPLETED / FAILED / CANCELLED / PARTIAL）一旦进入，
    不得被覆盖为其它非终态。
    """

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PARTIAL = "partial"


class TaskKind(str, Enum):
    """任务类型，对应各专业 Agent 的业务边界。"""

    STOCK_ANALYSIS = "stock_analysis"
    ASSET_ALLOCATION = "asset_allocation"
    PRODUCT_ANALYSIS = "product_analysis"
    CASUAL_CHAT = "casual_chat"
    DATA_PREPARATION = "data_preparation"
    DEBATE = "debate"
    SYNTHESIS = "synthesis"


class ExpertStatus(str, Enum):
    """专家结果状态，用于区分成功、降级、超时、取消与失败。"""

    SUCCESS = "success"
    DEGRADED = "degraded"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
