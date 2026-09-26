"""根图扇出拓扑：单/多领域同路径、崩溃可恢复、停止/截止、跨轮状态隔离。

本文件是阶段 1（可靠性地基）的验收测试，覆盖旧拓扑下不成立的语义：

- 单领域与多领域走**同一条**路径（``scope_tasks`` → ``Send`` → ``converge``），
  任务标识统一为 ``{run_id}:{domain}``；
- 领域任务是根图的独立 superstep：**每完成一个领域就有检查点**，因此"第 2 个领域
  崩溃后只重跑未完成领域"是可验证的（旧做法在一个节点里 ``invoke`` 未挂
  checkpointer 的子图，任何异常都要整轮重跑）；
- 停止/整轮截止在**下发前**与**专家模型轮次边界**两处生效，且已完成结论保留；
- 每轮派生状态收在 ``run`` 单键下并由 ``classify`` 整键重置：上一轮的
  ``trusted_content`` / 挂起表单不会泄漏到本轮；
- 告警分两级：提示级只披露，降级级才把 ``completed`` 翻成 ``partial``。
"""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from finance_agent.orchestration.budgets import RunBudgets
from tests.conftest import make_fake_supervisor_model
from finance_agent.orchestration.contracts import (
    RUN_CANCELLED_WARNING,
    TURN_DEADLINE_WARNING,
    BusinessDomain,
    DomainOutcome,
)
from finance_agent.orchestration.graphs.supervisor import (
    SupervisorDependencies,
    build_supervisor_graph,
    project_supervisor_state,
    reduce_run_status,
    run_of,
    task_id_of,
)
from finance_agent.orchestration.needs_input import build_form

STOCK = BusinessDomain.STOCK_RESEARCH.value
PRODUCT = BusinessDomain.PRODUCT_RESEARCH.value


class _Classifier:
    """按脚本输出分类结果；脚本用完返回空意图（不可能发生的兜底）。"""

    def __init__(self, *payloads: list[str], queries: dict[str, str] | None = None) -> None:
        self._payloads = list(payloads)
        self._queries = queries or {}

    def classify_intents(self, message: str, context_summary: str = "") -> dict:
        intents = self._payloads.pop(0) if self._payloads else []
        return {
            "intents": [
                {
                    "intent": intent,
                    "query": self._queries.get(intent, message),
                    "confidence": 0.99,
                }
                for intent in intents
            ],
            "uncertain_intents": [],
            "finance_related": True,
            "intent_source": "deepseek",
            "classification_error": {},
        }


class _Runner:
    """记录每次运行的上下文，按域返回可配置结论。"""

    def __init__(self, statuses: dict[str, str] | None = None) -> None:
        self.contexts: list = []
        self._statuses = statuses or {}

    def __call__(self, context) -> DomainOutcome:
        self.contexts.append(context)
        domain = context.task.domain
        status = self._statuses.get(domain.value, "success")
        if status == "needs_input":
            return DomainOutcome(
                task_id=context.task.task_id,
                domain=domain,
                status="needs_input",
                summary="请补充股票标的。",
                structured_data={"pending_input": build_form([(domain, ("stock_target",))])},
            )
        return DomainOutcome(
            task_id=context.task.task_id,
            domain=domain,
            status=status,
            summary=f"{domain.value} 完成",
        )


class _AnswerGatedRunner(_Runner):
    """只有收到期望标的时才成功，否则持续缺参（用于验证追问次数上限）。"""

    def __init__(self, expected: str) -> None:
        super().__init__()
        self._expected = expected

    def __call__(self, context) -> DomainOutcome:
        answers = dict(context.clarification_answers or {})
        self.contexts.append(context)
        if answers.get("stock_target") != self._expected:
            return DomainOutcome(
                task_id=context.task.task_id,
                domain=context.task.domain,
                status="needs_input",
                summary="请补充股票标的。",
                structured_data={
                    "pending_input": build_form(
                        [(context.task.domain, ("stock_target",))]
                    )
                },
            )
        return DomainOutcome(
            task_id=context.task.task_id,
            domain=context.task.domain,
            status="success",
            summary="已完成分析。",
        )


def _graph(*, intents, runner=None, checkpointer=None, budgets=None, should_stop=None,
           conversation_runner=None, queries=None, progress=None,
           semantic_check=None, trust_embeddings=None):
    return build_supervisor_graph(
        SupervisorDependencies(
            supervisor_model=make_fake_supervisor_model(),
            classifier=_Classifier(*intents, queries=queries),
            domain_runner=runner or _Runner(),
            conversation_runner=conversation_runner
            or (lambda state: {"final_response": "你好", "status": "success"}),
            # 注入空改写器：避免默认改写器（惰性构造 INTENT_MODEL）引入外部依赖。
            rewriter=lambda state, domains: {},
            should_stop=should_stop,
            budgets=budgets,
            progress=progress,
            semantic_check=semantic_check,
            trust_embeddings=trust_embeddings,
        ),
        checkpointer=checkpointer,
    )


def _inputs(thread_id: str = "t1", run_id: str = "run-1") -> dict:
    return {
        "user_message": "分析一下",
        "run_id": run_id,
        "customer_id": "CUST1",
        "conversation_id": "conv-1",
        "thread_id": thread_id,
    }


def _config(thread_id: str = "t1") -> dict:
    return {"configurable": {"thread_id": thread_id}}


# ── 单/多领域同路径 + 统一任务标识 ────────────────────────────────────────


def test_single_domain_uses_the_same_fanout_path():
    runner = _Runner()
    graph = _graph(intents=[["stock_analysis"]], runner=runner)

    result = graph.invoke(_inputs())

    assert [c.task.domain for c in runner.contexts] == [BusinessDomain.STOCK_RESEARCH]
    assert list(result["task_results"]) == [task_id_of("run-1", BusinessDomain.STOCK_RESEARCH)]
    assert run_of(result)["run_status"] == "completed"


def test_multi_domain_fans_out_in_parallel_with_one_task_per_domain():
    runner = _Runner()
    graph = _graph(intents=[["stock_analysis", "product_analysis"]], runner=runner)

    result = graph.invoke(_inputs())

    ran = sorted(c.task.domain.value for c in runner.contexts)
    assert ran == sorted([STOCK, PRODUCT])
    assert set(result["task_results"]) == {
        task_id_of("run-1", BusinessDomain.STOCK_RESEARCH),
        task_id_of("run-1", BusinessDomain.PRODUCT_RESEARCH),
    }
    assert run_of(result)["run_status"] == "completed"


def test_scoped_domain_queries_reach_task_descriptions_without_llm_rewriter():
    """每域子请求必须直达任务描述（改写器不可用时走确定性回退）。

    回归：状态搬家（routing 移入 ``run``）后 ``scoped_queries`` 曾仍读顶层，
    导致每个领域都拿到整句原话——一个域拿到"分析600519，另外看看基金"这种
    混了别的领域实体的描述，正是分段下发要避免的情况。
    """
    runner = _Runner()
    graph = _graph(
        intents=[["stock_analysis", "product_analysis"]],
        runner=runner,
        queries={
            "stock_analysis": "分析 600519 的基本面",
            "product_analysis": "分析华夏成长基金",
        },
    )

    graph.invoke({**_inputs(), "user_message": "分析 600519 的基本面，另外分析华夏成长基金"})

    goals = {c.task.domain: c.task.goal for c in runner.contexts}
    assert goals[BusinessDomain.STOCK_RESEARCH] == "分析 600519 的基本面"
    assert goals[BusinessDomain.PRODUCT_RESEARCH] == "分析华夏成长基金"


# ── 崩溃恢复：领域任务逐个落检查点 ───────────────────────────────────────


def test_completed_domain_results_survive_a_crash_of_a_later_domain():
    """崩溃时**已完成领域的结论必须已落检查点**。

    旧拓扑把整轮扇出放在一个节点函数里的嵌套 ``invoke`` 中，节点返回前不会有任何
    检查点，任何异常都要整轮重跑。现在每个领域任务是独立 superstep，因此"已经花过
    钱的那部分"是可恢复、可审计的：崩溃后检查点里已经有股票领域的结论，续跑也不会
    重做它。
    """
    calls: list[str] = []

    def flaky(context) -> DomainOutcome:
        calls.append(context.task.domain.value)
        if context.task.domain is BusinessDomain.PRODUCT_RESEARCH:
            # 用 BaseException 模拟"进程被杀"：领域节点内部的 except Exception
            # 只会把领域标记为 failed，不会中断进程。
            raise SystemExit("simulated process abort")
        return DomainOutcome(
            task_id=context.task.task_id,
            domain=context.task.domain,
            status="success",
            summary="股票已完成",
        )

    graph = _graph(
        intents=[["stock_analysis", "product_analysis"]],
        runner=flaky,
        checkpointer=InMemorySaver(),
    )
    config = _config("t-crash")

    with pytest.raises(BaseException):
        graph.invoke(_inputs("t-crash"), config)

    snapshot = graph.get_state(config)
    assert list(snapshot.values["task_results"]) == [
        task_id_of("run-1", BusinessDomain.STOCK_RESEARCH)
    ], "已完成领域的结论必须已随检查点落盘"

    graph.invoke(None, config)
    assert calls.count(STOCK) == 1, "已完成领域不得在续跑时重做"


# ── 缺参追问：可达上限、确定性计数 ───────────────────────────────────────


def test_resume_reruns_only_the_missing_domain_with_answer():
    runner = _AnswerGatedRunner(expected="600519")
    graph = _graph(intents=[["stock_analysis"]], runner=runner, checkpointer=InMemorySaver())
    config = _config()

    graph.invoke(_inputs(), config)
    result = graph.invoke(Command(resume={"stock_target": "600519"}), config)

    reruns = [c for c in runner.contexts if c.clarification_answers]
    assert len(reruns) == 1
    assert reruns[0].clarification_answers["stock_target"] == "600519"
    assert run_of(result)["run_status"] == "completed"


def test_clarify_rounds_are_capped_by_deterministic_counter():
    """弹窗总次数受配置上限约束：一直补不齐也不会无限追问。"""
    runner = _AnswerGatedRunner(expected="600519")
    graph = _graph(
        intents=[["stock_analysis"]],
        runner=runner,
        checkpointer=InMemorySaver(),
        budgets=RunBudgets(clarify_rounds=2),
    )
    config = _config("t-cap")

    first = graph.invoke(_inputs("t-cap"), config)
    assert first.get("__interrupt__"), "首次缺参必须挂起"
    assert run_of(first)["clarify_rounds"] == 1

    second = graph.invoke(Command(resume={"stock_target": "000001"}), config)
    assert second.get("__interrupt__"), "补答后仍缺参应重问一次"
    assert run_of(second)["clarify_rounds"] == 2

    third = graph.invoke(Command(resume={"stock_target": "000002"}), config)
    assert not third.get("__interrupt__"), "达到上限后不得再追问"
    assert run_of(third)["param_blocked"] is True
    assert run_of(third)["run_status"] == "partial"
    assert "needs_input_unresolved" in run_of(third)["degradations"]


def test_resume_resets_the_turn_deadline_after_user_think_time():
    """弹窗停留时间不属于计算预算：补答后整轮截止必须重新起算。

    否则用户花几分钟填表再提交，重跑会一开始就"已经超时"，直接降级收尾。
    """
    runner = _AnswerGatedRunner(expected="600519")
    graph = _graph(intents=[["stock_analysis"]], runner=runner, checkpointer=InMemorySaver())
    config = _config("t-deadline-reset")

    first = graph.invoke(_inputs("t-deadline-reset"), config)
    original_deadline = run_of(first)["deadline_monotonic"]
    assert original_deadline > 0
    assert first.get("__interrupt__")

    resumed = graph.invoke(Command(resume={"stock_target": "600519"}), config)

    assert run_of(resumed)["deadline_monotonic"] > original_deadline
    assert run_of(resumed)["run_status"] == "completed"


def test_without_checkpointer_degrades_to_clarification_instead_of_interrupting():
    graph = _graph(intents=[["stock_analysis"]], runner=_Runner({"stock_research": "needs_input"}))

    result = graph.invoke(_inputs())

    assert not result.get("__interrupt__")
    assert run_of(result)["param_blocked"] is True
    assert run_of(result)["run_status"] == "partial"
    assert run_of(result)["param_missing"]["missing"] == ["stock_research:stock_target"]


# ── 停止与整轮截止 ───────────────────────────────────────────────────────


def test_stop_before_dispatch_skips_all_domain_work_and_reports_cancelled():
    runner = _Runner()
    graph = _graph(intents=[["stock_analysis"]], runner=runner, should_stop=lambda: True)

    result = graph.invoke(_inputs())

    assert runner.contexts == [], "已请求停止时不得启动领域执行"
    assert run_of(result)["run_status"] == "cancelled"
    assert RUN_CANCELLED_WARNING in run_of(result)["degradations"]
    assert result["task_results"] == {}


def test_turn_deadline_marks_partial_with_explicit_reason():
    graph = _graph(
        intents=[["stock_analysis"]],
        runner=_Runner(),
        budgets=RunBudgets(turn_deadline=0.0001),
    )

    result = graph.invoke(_inputs())

    assert run_of(result)["run_status"] == "partial"
    assert TURN_DEADLINE_WARNING in run_of(result)["degradations"]


def test_domain_limitations_are_split_into_warning_and_degradation_levels():
    """运行级原因码升级为 degradation；领域内局限只做披露。"""

    def runner_with_notes(context) -> DomainOutcome:
        return DomainOutcome(
            task_id=context.task.task_id,
            domain=context.task.domain,
            status="partial",
            summary="部分完成",
            limitations=["react_step_limit", RUN_CANCELLED_WARNING],
        )

    graph = _graph(intents=[["stock_analysis"]], runner=runner_with_notes)

    result = graph.invoke(_inputs())
    run = run_of(result)

    assert RUN_CANCELLED_WARNING in run["degradations"]
    assert "react_step_limit" in run["warnings"]
    assert "react_step_limit" not in run["degradations"]
    assert run["run_status"] == "cancelled"


# ── 跨轮状态隔离 ────────────────────────────────────────────────────────


def test_run_scoped_state_does_not_leak_across_turns():
    """上一轮的受信标记与挂起表单不得影响下一轮（历史两次事故的回归）。"""
    graph = _graph(
        intents=[["casual_chat"], ["stock_analysis"]],
        conversation_runner=lambda state: {
            "final_response": "什么是操纵市场？",
            "status": "success",
            "cited_faq": True,
            "cited_sources": ["操纵市场是指……"],
            "warnings": ["faq_note"],
        },
        checkpointer=InMemorySaver(),
    )
    config = _config("t-leak")

    first = graph.invoke(_inputs("t-leak", run_id="run-1"), config)
    assert run_of(first)["trusted_content"] is True

    second = graph.invoke(_inputs("t-leak", run_id="run-2"), config)
    run = run_of(second)

    assert run["trusted_content"] is False, "受信标记必须随轮次重置"
    assert run["trusted_sources"] == []
    assert "faq_note" not in run["warnings"]
    assert run["param_missing"] == {}
    assert run["deadline_monotonic"] > 0


# ── 告警分级对 run_status 的影响（纯函数） ───────────────────────────────


def _outcome(status: str) -> DomainOutcome:
    return DomainOutcome(
        task_id="t", domain=BusinessDomain.STOCK_RESEARCH, status=status, summary="s",
    )


def test_reduce_run_status_ignores_info_level_notes_but_honours_degradations():
    assert reduce_run_status([_outcome("success")], []) == "completed"
    assert reduce_run_status([_outcome("success")], ["task_rewrite_dropped_entities:x"]) == "partial"
    assert reduce_run_status([_outcome("success")], [RUN_CANCELLED_WARNING]) == "cancelled"
    assert reduce_run_status([_outcome("failed")], []) == "failed"
    assert reduce_run_status([], []) == "partial"


# ── 进度事件：节点边界必发，细粒度到领域 ─────────────────────────────────


def test_progress_stages_are_emitted_per_domain_and_per_phase():
    """图内不再"只有宿主发进度"：路由/拆解/各领域/合规都有 stage 事件。"""
    seen: list[str] = []
    graph = _graph(
        intents=[["stock_analysis", "product_analysis"]],
        progress=lambda stage, message: seen.append(stage),
    )

    graph.invoke(_inputs())

    assert seen[0] == "routing"
    assert "scope" in seen
    assert f"domain:{STOCK}" in seen
    assert f"domain:{PRODUCT}" in seen
    assert seen[-1] == "compliance"


def test_progress_failure_never_breaks_the_turn():
    """进度只影响观感：回调抛错不得改变业务结果。"""

    def broken(stage: str, message: str) -> None:
        raise RuntimeError("sse closed")

    graph = _graph(intents=[["stock_analysis"]], progress=broken)

    result = graph.invoke(_inputs())

    assert run_of(result)["run_status"] == "completed"
    assert run_of(result)["final_response"]


# ── 合规出口接线 ────────────────────────────────────────────────────────


def test_semantic_check_failure_is_fail_closed_at_the_compliance_exit():
    """语义校验不可用时必须拦截，绝不把未校验草稿当结果下发。"""
    from finance_agent.orchestration.graphs.compliance import (
        BLOCKED_RESPONSE,
        ComplianceUnavailable,
    )

    def broken(text: str) -> list[str]:
        raise ComplianceUnavailable("semantic_check_failed")

    graph = _graph(intents=[["stock_analysis"]], semantic_check=broken)

    projected = project_supervisor_state(graph.invoke(_inputs()))

    assert projected["response"] == BLOCKED_RESPONSE
    assert projected["run_status"] == "failed"
    assert "compliance_unavailable" in projected["warnings"]


def test_conversation_trusted_sources_reach_the_compliance_exit():
    """FAQ 原文随 state 流到合规出口，并按句级判定豁免（只审计不改写）。"""
    reply = "什么是操纵市场？"

    class _SameTextEmbedder:
        def embed_query(self, text: str) -> list[float]:
            return [1.0, 0.0]

    graph = _graph(
        intents=[["casual_chat"]],
        conversation_runner=lambda state: {
            "final_response": reply,
            "status": "success",
            "cited_faq": True,
            "cited_sources": [reply],
        },
        trust_embeddings=_SameTextEmbedder(),
    )

    result = graph.invoke(_inputs())
    run = run_of(result)

    assert run["compliance"]["action"] == "audited"
    assert run["compliance"]["trusted_spans"] == 1
    assert run["final_response"] == reply, "受信原文必须逐字保留"


# ── 响应投影 ────────────────────────────────────────────────────────────


def test_projection_exposes_run_scoped_fields_and_keeps_contract_keys():
    runner = _Runner()
    graph = _graph(intents=[["stock_analysis"]], runner=runner)

    projected = project_supervisor_state(
        graph.invoke({**_inputs(), "user_profile": {"risk_preference": "稳健"}}),
        conversation_id="conv-1",
    )

    assert projected["conversation_id"] == "conv-1"
    assert projected["user_profile"] == {"risk_preference": "稳健"}
    assert projected["response"]
    assert projected["pending_input"] is None
    # 计划层删除后这些键保留但不再写入。
    assert projected["task_dispatch"] == []
    assert projected["tasks"] == []
