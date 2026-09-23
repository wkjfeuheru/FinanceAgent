"""V2 编排层的强类型运行契约。"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from finance_agent.contracts import RunStatus


class BusinessDomain(str, Enum):
    STOCK_RESEARCH = "stock_research"
    MARKET_INSIGHT = "market_insight"
    PRODUCT_RESEARCH = "product_research"
    # 用户自有账户与持仓的只读问答；下单/充值只能走 REST，不经对话。
    ACCOUNT_PORTFOLIO = "account_portfolio"


class ExecutionMode(str, Enum):
    CONVERSATION = "conversation"
    DOMAIN_REACT = "domain_react"
    PLAN_EXECUTE = "plan_execute"
    CLARIFY = "clarify"


# 全局硬上限：环境变量允许在默认值之上调紧或放宽，但不得超过这些天花板。
# 上限来自设计预算（ReAct 四轮/计划八任务/重规划两次/合规一次改写/整图 32 步）
# 的两倍冗余——足够覆盖"按 profile 加预算"的场景，又保证一个写错的环境变量
# 不能把预算放大到失去防护意义。
REACT_STEPS_HARD_CAP = 8
PLAN_TASKS_HARD_CAP = 16
REPLANS_HARD_CAP = 4
COMPLIANCE_REWRITES_HARD_CAP = 2
GRAPH_STEPS_HARD_CAP = 128


class RunBudgets(BaseModel):
    """整轮运行的受校验预算（设计 §14）。

    数值唯一来源是 ``config`` 的 ``ORCHESTRATION_*`` 环境变量；本模型负责
    校验（落在 [下限, 全局硬上限] 区间内），禁止调用方传入越界值。
    ``AdvisorSystem`` 创建一次并注入 Conversation、Plan、Compliance 与根图。
    """

    react_steps: int = Field(default=4, ge=1, le=REACT_STEPS_HARD_CAP)
    plan_tasks: int = Field(default=8, ge=1, le=PLAN_TASKS_HARD_CAP)
    replans: int = Field(default=2, ge=0, le=REPLANS_HARD_CAP)
    compliance_rewrites: int = Field(default=1, ge=0, le=COMPLIANCE_REWRITES_HARD_CAP)
    graph_steps: int = Field(default=32, ge=1, le=GRAPH_STEPS_HARD_CAP)

    @classmethod
    def from_config(cls) -> "RunBudgets":
        """从 ``config.ORCHESTRATION_*`` 读取预算；越界值在构造时被拒绝。"""
        from finance_agent import config

        return cls(
            react_steps=config.ORCHESTRATION_REACT_STEPS,
            plan_tasks=config.ORCHESTRATION_PLAN_TASKS,
            replans=config.ORCHESTRATION_REPLANS,
            compliance_rewrites=config.ORCHESTRATION_COMPLIANCE_REWRITES,
            graph_steps=config.ORCHESTRATION_GRAPH_STEPS,
        )


class ExecutionProfile(BaseModel):
    """统一 Planner–Executor 图的一种受校验配置实例。

    ``react``：受限 ReAct（会话、单领域工作流），无重规划。
    ``plan_execute``：受限多步骤计划，可选重规划（``replan_enabled=True``
    时 ``max_replans`` 必须至少为 1）。
    ``max_steps`` 独立于 ``RunBudgets`` 的全局上限受校验，profile 之间互不
    借用预算；根图只根据路由选择 profile，不直接传自由数值。
    """

    mode: Literal["react", "plan_execute"]
    max_steps: int = Field(ge=1, le=GRAPH_STEPS_HARD_CAP)
    replan_enabled: bool = False
    max_replans: int = Field(default=0, ge=0, le=REPLANS_HARD_CAP)
    # operation 白名单范围：领域枚举值之一，或跨领域计划专用的 cross_domain。
    operation_scope: Literal[
        "conversation", "stock", "market", "product", "account", "cross_domain",
    ] = "conversation"

    @model_validator(mode="after")
    def _validate_mode_invariants(self) -> "ExecutionProfile":
        if self.mode == "react" and self.replan_enabled:
            raise ValueError("react profile must not enable replan")
        if self.replan_enabled and self.max_replans < 1:
            raise ValueError("replan_enabled requires max_replans >= 1")
        if self.mode == "plan_execute" and self.operation_scope != "cross_domain":
            raise ValueError("plan_execute profile must use cross_domain scope")
        if self.mode == "react" and self.operation_scope == "cross_domain":
            raise ValueError("react profile must be scoped to a single domain")
        return self


class ArtifactRef(BaseModel):
    uri: str
    content_hash: str = ""
    media_type: str = "application/json"


class AsyncJobRef(BaseModel):
    job_id: str
    kind: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    task_id: str


class PlanTask(BaseModel):
    task_id: str
    domain: BusinessDomain
    goal: str
    instruction: str
    depends_on: list[str] = Field(default_factory=list)
    input_refs: list[ArtifactRef] = Field(default_factory=list)
    expected_output: str


class DomainOutcome(BaseModel):
    task_id: str
    domain: BusinessDomain
    status: Literal["success", "partial", "processing", "failed"]
    summary: str
    structured_data: dict[str, Any] = Field(default_factory=dict)
    evidence: list[ArtifactRef] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    pending_jobs: list[AsyncJobRef] = Field(default_factory=list)


class DomainTaskContext(BaseModel):
    task: PlanTask
    thread_id: str
    customer_id: str
    conversation_id: str
    user_message: str
    upstream_results: dict[str, DomainOutcome] = Field(default_factory=dict)
    # 本轮 run_id：异步量化任务提交时需要，用于持久化 job 引用并支持恢复。
    # 默认空串保持既有构造点兼容（旧调用方不传也不报错）。
    run_id: str = ""
    # 本轮抽取到的领域参数（含弹窗补填）：领域 handler 映射为 ``intent_slots``。
    params: dict[str, Any] = Field(default_factory=dict)
    # 用户画像卡快照。此前领域 handler 硬编码 ``{}``，导致 profile_complete 恒假、
    # personalization_status 恒为 research_candidate；此处打通注入。
    user_profile: dict[str, Any] = Field(default_factory=dict)


class ExecutionPlan(BaseModel):
    tasks: list[PlanTask]


class PlanDecision(BaseModel):
    action: Literal["dispatch", "replan", "finish"]
    plan: ExecutionPlan | None = None


class RoutingDecision(BaseModel):
    domains: list[BusinessDomain]
    execution_mode: Literal["conversation", "domain_react", "plan_execute", "clarify"]
    clarification: str = ""
    # 分类协议错误或模型不可用时置为非空；此时不得静默猜测业务领域。
    error_code: str = ""
    # 每个业务领域对应的**该领域子请求**（来自分类器的 per-intent query）。
    # 复合请求必须按领域下发子请求，否则某领域会拿到整句（含其它领域实体）。
    domain_queries: dict[str, str] = Field(default_factory=dict)
    # 未执行部分的提示（如低置信度意图需澄清），用于向用户明示而非静默丢弃。
    warnings: list[str] = Field(default_factory=list)


class ReactDecision(BaseModel):
    action: Literal["tool", "final"]
    tool_name: str = ""
    tool_input: dict[str, Any] = Field(default_factory=dict)
    final_text: str = ""


class ComplianceDecision(BaseModel):
    action: Literal["passed", "rewritten", "blocked", "audited"]
    response: str
    reason_codes: list[str]
    rewrite_count: int


class NodeError(BaseModel):
    code: str
    category: Literal["transient", "validation", "dependency", "compliance", "cancelled"]
    retryable: bool
    safe_message: str
    internal_ref: str


# ── 状态字符串映射（集中定义）────────────────────────────────────────────────
# 这些映射此前散落在 supervisor_graph / domains / orchestrator 四处各自复制一份，
# 键写错只能靠运行时发现。此处唯一登记，取值统一对齐 RunStatus 枚举。
# 键一律保留裸字符串：上游写入的就是 Literal 字符串（DomainOutcome.status /
# intent_results 的 status / AsyncJobRef.status），枚举成员作键虽在比较上等价，
# 但迭代与序列化时的形状不同（str(member) 不是 value），容易误用。

#: 领域结论状态（``DomainOutcome.status``）→ Supervisor Graph 运行状态。
#: "processing"（异步量化任务进行中）在 RunStatus 中无同名成员，原样保留。
DOMAIN_STATUS_TO_RUN_STATUS: dict[str, str] = {
    "success": RunStatus.COMPLETED.value,
    "partial": RunStatus.PARTIAL.value,
    "processing": "processing",
    "failed": RunStatus.FAILED.value,
}

#: 域内 ``intent_results[...]["status"]`` → 领域结论状态。
#: 语义与 DOMAIN_STATUS_TO_RUN_STATUS 不同（意图结果→领域结论，而非领域结论→运行
#: 状态），故独立命名、不合并。
INTENT_STATUS_TO_DOMAIN_STATUS: dict[str, str] = {
    "success": "success",
    "degraded": "partial",
    "failed": "failed",
}
#: 未登记的意图状态一律按降级处理（保守：不伪报成功）。
DEFAULT_INTENT_DOMAIN_STATUS = "partial"
#: 意图状态中属于"降级"的一类：命中即把领域结论降为 partial。
DEGRADED_INTENT_STATUSES: frozenset[str] = frozenset({"degraded", "failed"})

#: 异步量化任务状态（``AsyncJobRef.status``）→ 运行状态。
JOB_STATUS_TO_RUN_STATUS: dict[str, str] = {
    "queued": "processing",
    "running": "processing",
    "completed": RunStatus.COMPLETED.value,
    "failed": RunStatus.FAILED.value,
    "cancelled": RunStatus.CANCELLED.value,
}
#: 未知/未上报的任务状态按"仍在进行中"处理（不得伪报成功）。
DEFAULT_JOB_RUN_STATUS = "processing"
#: 执行器上报的"降级"运行状态：命中时可覆盖结论集合的判定。
DEGRADED_RUN_STATUSES: frozenset[str] = frozenset(
    {RunStatus.FAILED.value, RunStatus.PARTIAL.value}
)
