"""V2 编排层的强类型运行契约。"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class BusinessDomain(str, Enum):
    STOCK_RESEARCH = "stock_research"
    MARKET_INSIGHT = "market_insight"
    PRODUCT_RESEARCH = "product_research"


class ExecutionMode(str, Enum):
    CONVERSATION = "conversation"
    DOMAIN_REACT = "domain_react"
    PLAN_EXECUTE = "plan_execute"
    CLARIFY = "clarify"


class RunBudgets(BaseModel):
    react_steps: int = Field(default=4, ge=0, le=4)
    plan_tasks: int = Field(default=8, ge=0, le=8)
    replans: int = Field(default=2, ge=0, le=2)
    compliance_rewrites: int = Field(default=1, ge=0, le=1)
    graph_steps: int = Field(default=32, ge=1, le=32)


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
    action: Literal["passed", "rewritten", "blocked"]
    response: str
    reason_codes: list[str]
    rewrite_count: int


class NodeError(BaseModel):
    code: str
    category: Literal["transient", "validation", "dependency", "compliance", "cancelled"]
    retryable: bool
    safe_message: str
    internal_ref: str
