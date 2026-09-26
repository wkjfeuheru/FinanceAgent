"""受校验的编排运行预算配置。"""

from pydantic import BaseModel, Field


# 配置可以调紧或放宽，但不能越过这些上限。
REACT_STEPS_HARD_CAP = 16
DOMAINS_HARD_CAP = 16
COMPLIANCE_REWRITES_HARD_CAP = 2
CLARIFY_ROUNDS_HARD_CAP = 4
GRAPH_STEPS_HARD_CAP = 128


class RunBudgets(BaseModel):
    """整轮运行的受校验预算，数值来源于 ``config.ORCHESTRATION_*``。"""

    react_steps: int = Field(default=4, ge=1, le=REACT_STEPS_HARD_CAP)
    #: 单轮最多扇出的业务领域数（跨领域扇出上限；领域总数为 4）。
    max_domains: int = Field(default=4, ge=1, le=DOMAINS_HARD_CAP)
    compliance_rewrites: int = Field(default=1, ge=0, le=COMPLIANCE_REWRITES_HARD_CAP)
    #: 缺参追问的总弹窗上限（首次 + 重问），确定性计数。
    clarify_rounds: int = Field(default=2, ge=1, le=CLARIFY_ROUNDS_HARD_CAP)
    graph_steps: int = Field(default=32, ge=1, le=GRAPH_STEPS_HARD_CAP)
    #: 整轮墙钟上限（秒）；图内按此值写入 deadline，<=0 表示不限。
    turn_deadline: float = Field(default=120.0, gt=0)

    @classmethod
    def from_config(cls) -> "RunBudgets":
        """从配置读取预算；越界值在构造时被拒绝。"""
        from finance_agent.infrastructure import settings as config

        return cls(
            react_steps=config.ORCHESTRATION_REACT_STEPS,
            max_domains=config.ORCHESTRATION_MAX_DOMAINS,
            compliance_rewrites=config.ORCHESTRATION_COMPLIANCE_REWRITES,
            clarify_rounds=config.ORCHESTRATION_CLARIFY_ROUNDS,
            graph_steps=config.ORCHESTRATION_GRAPH_STEPS,
            turn_deadline=config.ORCHESTRATION_TURN_DEADLINE,
        )


__all__ = [
    "CLARIFY_ROUNDS_HARD_CAP",
    "COMPLIANCE_REWRITES_HARD_CAP",
    "DOMAINS_HARD_CAP",
    "GRAPH_STEPS_HARD_CAP",
    "REACT_STEPS_HARD_CAP",
    "RunBudgets",
]
