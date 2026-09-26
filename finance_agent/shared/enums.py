"""数据流契约枚举：运行状态、任务类型与专家结果状态。"""

from __future__ import annotations

from enum import Enum


class RunStatus(str, Enum):
    """Agent 运行状态。

    终态（COMPLETED / FAILED / CANCELLED / PARTIAL）一旦进入，
    不得被覆盖为其它非终态。AWAITING_INPUT 是非终态：缺参追问已挂起，
    等待用户补充参数后在同一线程 resume。
    """

    RUNNING = "running"
    AWAITING_INPUT = "awaiting_input"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PARTIAL = "partial"


class TaskKind(str, Enum):
    """任务类型，对应各专业 Agent 的业务边界。"""

    STOCK_ANALYSIS = "stock_analysis"
    PRODUCT_ANALYSIS = "product_analysis"
    CASUAL_CHAT = "casual_chat"
    DATA_PREPARATION = "data_preparation"
    SYNTHESIS = "synthesis"


class IntentKind(str, Enum):
    """用户请求的业务意图。

    与分类器的意图注册表（``orchestrator/intent.py`` 的 ``_INTENTS``）必须同源：
    新增意图必须同时在此登记，否则按 expert_name 推导 intent 的旧结果会漏掉它
    （``tests/test_supervisor_graph_routing.py`` 的注册表一致性测试守护这一点）。
    """

    STOCK_ANALYSIS = "stock_analysis"
    STOCK_RECOMMENDATION = "stock_recommendation"
    PRODUCT_ANALYSIS = "product_analysis"
    # 用户自有账户与持仓的配置诊断及优化参考。
    PORTFOLIO_ANALYSIS = "portfolio_analysis"
    CASUAL_CHAT = "casual_chat"


class TaskStatus(str, Enum):
    """单个任务在调度生命周期中的状态。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    DEGRADED = "degraded"
    FAILED = "failed"
    TIMEOUT = "timeout"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class ExpertStatus(str, Enum):
    """专家结果状态，用于区分成功、降级、超时、取消与失败。"""

    SUCCESS = "success"
    DEGRADED = "degraded"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
