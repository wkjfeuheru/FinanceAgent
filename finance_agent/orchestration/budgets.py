"""受校验的编排运行预算配置。"""

from pydantic import BaseModel, Field, model_validator


# 配置可以调紧或放宽，但不能越过这些上限。
REACT_STEPS_HARD_CAP = 16
DOMAINS_HARD_CAP = 16
COMPLIANCE_REWRITES_HARD_CAP = 2
CLARIFY_ROUNDS_HARD_CAP = 4
GRAPH_STEPS_HARD_CAP = 128
#: 板块筛选的数据量上限：每只候选要逐只取数（约 5 次 provider 调用），
#: 放开就等于让整轮必然撞上 turn_deadline。
SCREEN_EVALUATIONS_HARD_CAP = 20
SCREEN_RESULTS_HARD_CAP = 10


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
    #: 板块/概念筛选：每轮最多评估多少只成分、最终返回多少只候选。
    screen_max_evaluations: int = Field(
        default=10, ge=1, le=SCREEN_EVALUATIONS_HARD_CAP,
    )
    screen_max_results: int = Field(default=5, ge=1, le=SCREEN_RESULTS_HARD_CAP)

    @model_validator(mode="after")
    def _screen_results_within_evaluations(self) -> "RunBudgets":
        """返回的候选只能来自已评估的标的，否则预算口径自相矛盾。"""
        if self.screen_max_results > self.screen_max_evaluations:
            raise ValueError("screen_max_results 不得大于 screen_max_evaluations")
        return self

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
            screen_max_evaluations=config.ORCHESTRATION_SCREEN_MAX_EVALUATIONS,
            screen_max_results=config.ORCHESTRATION_SCREEN_MAX_RESULTS,
        )


__all__ = [
    "CLARIFY_ROUNDS_HARD_CAP",
    "COMPLIANCE_REWRITES_HARD_CAP",
    "DOMAINS_HARD_CAP",
    "GRAPH_STEPS_HARD_CAP",
    "REACT_STEPS_HARD_CAP",
    "SCREEN_EVALUATIONS_HARD_CAP",
    "SCREEN_RESULTS_HARD_CAP",
    "RunBudgets",
]
