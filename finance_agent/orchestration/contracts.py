"""V2 编排层的强类型运行契约。"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

from finance_agent.domains.contracts import BusinessDomain
from finance_agent.shared.contracts import AsyncJobRef, RunStatus

# 领域身份（枚举）的唯一定义在 ``domains/contracts.py``：领域是领域自身的属性，
# 编排层只复用。此处 re-export 以保持既有 ``from ...orchestration.contracts import
# BusinessDomain`` 的进口点不变（orchestration/api/application/tests 均依赖它）。

#: 用户主动停止本轮生成时写入的降级原因码。
#: 它必须可被 ``reduce_run_status`` 识别（前端要区分"停止"与"出错"），
#: 也必须能从专家子图的 limitations 一路冒泡上来——专家在模型轮次边界
#: 检测到停止后用同一个字符串登记，因此这里是唯一事实源。
RUN_CANCELLED_WARNING = "cancelled_by_user"
#: 整轮墙钟上限耗尽时写入的降级原因码（保留已完成结论并以 partial 收尾）。
TURN_DEADLINE_WARNING = "turn_deadline_exceeded"


class ExecutionMode(str, Enum):
    """顶层执行模式（Supervisor 路由分支选择器，与领域内分析路径是两个概念）。

    ``DOMAIN_WORKFLOW``：业务领域直达该领域的 ReAct 专家（历史上叫
    ``domain_react``，曾短暂改名以区分当时的确定性工作流；专家改回 ReAct 后
    ``domain_workflow`` 保留为对外取值）。单领域与多领域共用本模式：跨领域由
    根图 ``Send`` 扇出，不再有独立的"计划执行"模式。
    """

    CONVERSATION = "conversation"
    DOMAIN_WORKFLOW = "domain_workflow"
    CLARIFY = "clarify"


class ArtifactRef(BaseModel):
    uri: str
    content_hash: str = ""
    media_type: str = "application/json"


class PlanTask(BaseModel):
    """下发给单个领域专家的任务描述（每个业务领域恰好一条）。

    ``depends_on`` / ``input_refs`` 已随计划层删除：跨领域扇出是**并行**的，
    不存在领域间依赖，``upstream_results`` 因此恒为空。保留 ``expected_output``
    作为任务契约的一部分（领域结论的形态声明）。
    """

    task_id: str
    domain: BusinessDomain
    goal: str
    instruction: str
    expected_output: str


class DomainOutcome(BaseModel):
    """领域专家的统一结论。

    ``needs_input``：专家在 ReAct 循环中通过 ``request_user_input`` 工具明确表示
    无法继续（缺必填标的、名称歧义等），携带 ``structured_data.pending_input``
    表单。它不是终态——supervisor 的 ``converge``/``ask`` 节点据此弹出追问、拿到
    答案后按域重跑，再把最终结论交给汇合/合规出口。
    """

    task_id: str
    domain: BusinessDomain
    status: Literal["success", "partial", "processing", "failed", "needs_input"]
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
    # 整轮墙钟截止（``time.monotonic()`` 基准，0 表示不限）。宿主据此构造
    # "停止/截止查询"下发给专家，使专家在模型轮次边界能自行退出——截止时间
    # 需要跨 RunnableConfig 边界传递，因此以**数值**而非可调用对象承载。
    turn_deadline_monotonic: float = 0.0
    # 【废弃】旧 supervisor 参数抽取通道。专家改为 ReAct 后自行解析参数，
    # 该字段保留仅为兼容仍会传入的老调用点与历史 checkpoint，不再被读取。
    params: dict[str, Any] = Field(default_factory=dict)
    # 【废弃】旧的领域子意图（分类器产出、驱动确定性模式选择）。子意图体系已删除。
    sub_intent: str = ""
    # 用户画像卡快照。此前领域 handler 硬编码 ``{}``，导致 profile_complete 恒假、
    # personalization_status 恒为 research_candidate；此处打通注入。
    user_profile: dict[str, Any] = Field(default_factory=dict)
    # 本轮弹窗补填的答案（``{domain}:{field}`` → 值）。专家重跑时据此继续，
    # 由 supervisor 的缺参重跑（``ask`` → ``domain_worker``）在 resume 后填充。
    clarification_answers: dict[str, Any] = Field(default_factory=dict)


class RoutingDecision(BaseModel):
    domains: list[BusinessDomain]
    execution_mode: Literal["conversation", "domain_workflow", "clarify"]
    clarification: str = ""
    # 分类协议错误或模型不可用时置为非空；此时不得静默猜测业务领域。
    error_code: str = ""
    # 每个业务领域对应的**该领域子请求**（来自分类器的 per-intent query）。
    # 复合请求必须按领域下发子请求，否则某领域会拿到整句（含其它领域实体）。
    domain_queries: dict[str, str] = Field(default_factory=dict)
    # 未执行部分的提示（如低置信度意图需澄清），用于向用户明示而非静默丢弃。
    warnings: list[str] = Field(default_factory=list)
    # 本轮用户**自述**事实的候选（分类器同一次调用产出：``{field, value, quote}``）。
    # 编排层只负责透传，落库前的确定性门控在
    # ``AgentMemoryContext.apply_model_facts``；它随 ``run.routing`` 进 checkpoint，
    # 但**不进** /api/chat 的响应契约。
    profile_facts: list[dict[str, Any]] = Field(default_factory=list)


class ComplianceDecision(BaseModel):
    action: Literal["passed", "rewritten", "blocked", "audited"]
    response: str
    reason_codes: list[str]
    rewrite_count: int


# ── 状态字符串映射（集中定义）────────────────────────────────────────────────
# 这些映射此前散落在 supervisor_graph / domains / orchestrator 四处各自复制一份，
# 键写错只能靠运行时发现。此处唯一登记，取值统一对齐 RunStatus 枚举。
# 键一律保留裸字符串：上游写入的就是 Literal 字符串（DomainOutcome.status /
# intent_results 的 status / AsyncJobRef.status），枚举成员作键虽在比较上等价，
# 但迭代与序列化时的形状不同（str(member) 不是 value），容易误用。

#: 领域结论状态（``DomainOutcome.status``）→ Supervisor Graph 运行状态。
#: "processing"（异步量化任务进行中）在 RunStatus 中无同名成员，原样保留。
#: "needs_input" 同理：它不是终态，正常路径由 supervisor 的缺参判定节点拦截并转为
#: awaiting_input 追问；此处兜底映射保证任何遗漏路径也不会把它当成功放行。
DOMAIN_STATUS_TO_RUN_STATUS: dict[str, str] = {
    "success": RunStatus.COMPLETED.value,
    "partial": RunStatus.PARTIAL.value,
    "processing": "processing",
    "needs_input": RunStatus.AWAITING_INPUT.value,
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
