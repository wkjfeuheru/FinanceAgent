"""LLM Supervisor 决策节点：handoff 选域、候选集硬约束、多领域并行扇出。

根图的 ``supervisor`` 节点用 ``create_agent`` + ``transfer_to_<domain>`` handoff
工具选定业务领域，再由节点统一构造根图 ``Send``。本文件守住三类语义：

1. **候选集是硬上界**：LLM 只能选择分类器给出的候选领域，越界的 handoff 调用被
   拒绝并丢弃，不会凭空新增领域；
2. **多领域并行扇出**：同一轮并行 handoff 多个领域时全部执行（不是只留最后一个）；
3. **回落**：LLM 未选出任何有效领域时回退候选全集，绝不静默不执行。
"""

from __future__ import annotations

from finance_agent.orchestration.contracts import BusinessDomain, DomainOutcome
from finance_agent.orchestration.graphs.supervisor import (
    SupervisorDependencies,
    build_supervisor_graph,
    run_of,
    routing_of,
)
from tests.conftest import make_fake_supervisor_model


class _Classifier:
    def __init__(self, *intents: str) -> None:
        self._intents = list(intents)

    def classify_intents(self, message: str, context_summary: str = "") -> dict:
        return {
            "intents": [
                {"intent": intent, "query": message, "confidence": 0.99}
                for intent in self._intents
            ],
            "uncertain_intents": [],
            "finance_related": True,
            "intent_source": "deepseek",
            "classification_error": {},
        }


def _runner() -> tuple[list[BusinessDomain], object]:
    ran: list[BusinessDomain] = []

    def domain_runner(context) -> DomainOutcome:
        ran.append(context.task.domain)
        return DomainOutcome(
            task_id=context.task.task_id,
            domain=context.task.domain,
            status="success",
            summary=f"{context.task.domain.value} 完成",
        )

    return ran, domain_runner


def _graph(*intents: str, select=None, runner=None):
    _, default_runner = _runner()
    return build_supervisor_graph(
        SupervisorDependencies(
            supervisor_model=make_fake_supervisor_model(select),
            classifier=_Classifier(*intents),
            domain_runner=runner or default_runner,
            rewriter=lambda state, domains: {},
        )
    )


def test_llm_selects_single_domain_and_fans_out_once():
    ran, runner = _runner()
    graph = _graph("stock_analysis", runner=runner)

    result = graph.invoke({"user_message": "分析600519", "run_id": "run-1"})

    assert ran == [BusinessDomain.STOCK_RESEARCH]
    assert list(result["task_results"]) == ["run-1:stock_research"]
    assert run_of(result)["run_status"] == "completed"


def test_llm_parallel_handoffs_fan_out_to_every_selected_domain():
    """同一轮并行 handoff 多个领域：**全部**执行，而不是只保留最后一个。"""
    ran, runner = _runner()
    graph = _graph("stock_analysis", "product_analysis", runner=runner)

    result = graph.invoke({"user_message": "分析600519并看110011", "run_id": "run-2"})

    assert sorted(ran) == [BusinessDomain.PRODUCT_RESEARCH, BusinessDomain.STOCK_RESEARCH]
    assert set(result["task_results"]) == {"run-2:stock_research", "run-2:product_research"}
    assert run_of(result)["run_status"] == "completed"


def test_llm_cannot_select_a_domain_outside_the_candidate_set():
    """候选集是硬上界：LLM 选择候选外的领域被拒，回退到候选全集。"""
    ran, runner = _runner()
    # 分类器只给出 stock 候选，但假模型尝试 handoff product。
    graph = _graph("stock_analysis", select=["product_research"], runner=runner)

    result = graph.invoke({"user_message": "分析600519", "run_id": "run-3"})

    assert ran == [BusinessDomain.STOCK_RESEARCH], "候选外领域不得执行"
    assert list(result["task_results"]) == ["run-3:stock_research"]


def test_llm_selection_subset_of_candidates_is_respected():
    """LLM 可在候选集内**少选**：候选有两个领域但只选一个时，只执行被选中的那个。"""
    ran, runner = _runner()
    graph = _graph("stock_analysis", "product_analysis", select=["stock_research"], runner=runner)

    result = graph.invoke({"user_message": "分析600519并看110011", "run_id": "run-4"})

    assert ran == [BusinessDomain.STOCK_RESEARCH]
    assert list(result["task_results"]) == ["run-4:stock_research"]


def test_conversation_branch_never_reaches_the_supervisor_node():
    """闲聊走 conversation 分支，不经过 supervisor 决策（无领域任务）。"""
    ran, runner = _runner()
    graph = build_supervisor_graph(
        SupervisorDependencies(
            supervisor_model=make_fake_supervisor_model(),
            classifier=_Classifier("casual_chat"),
            domain_runner=runner,
            conversation_runner=lambda state: {"final_response": "你好", "status": "success"},
            rewriter=lambda state, domains: {},
        )
    )

    result = graph.invoke({"user_message": "你好", "run_id": "run-5"})

    assert ran == []
    assert run_of(result)["final_response"] == "你好"


def test_handoff_description_does_not_override_deterministic_rewrite():
    """LLM 只选域：确定性改写（含实体保真）到达专家，不被 handoff 描述覆盖。

    即便假模型给出一条通用 handoff 描述，注入的确定性改写结果仍必须胜出。
    """
    seen: dict = {}

    def domain_runner(context) -> DomainOutcome:
        seen["goal"] = context.task.goal
        return DomainOutcome(
            task_id=context.task.task_id,
            domain=context.task.domain,
            status="success",
            summary="完成",
        )

    graph = build_supervisor_graph(
        SupervisorDependencies(
            supervisor_model=make_fake_supervisor_model(),
            classifier=_Classifier("stock_analysis"),
            domain_runner=domain_runner,
            rewriter=lambda state, domains: {"stock_research": "分析 600519 的基本面"},
        )
    )

    graph.invoke({"user_message": "分析 600519", "run_id": "run-6"})

    assert seen["goal"] == "分析 600519 的基本面"


def test_fallback_selects_candidate_set_when_llm_returns_no_handoff():
    """LLM 一次 handoff 都没给出（模型漂移）：回退候选全集，绝不静默不执行。"""
    from langchain_core.messages import AIMessage as _AI
    from langchain_core.outputs import ChatGeneration, ChatResult

    from tests.conftest import _fake_chat_models

    base = _fake_chat_models.GenericFakeChatModel

    class _NoHandoff(base):  # type: ignore[misc, valid-type]
        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            return ChatResult(generations=[ChatGeneration(message=_AI(content="我不知道怎么选。"))])

    ran, runner = _runner()
    graph = build_supervisor_graph(
        SupervisorDependencies(
            supervisor_model=_NoHandoff(messages=iter([])),
            classifier=_Classifier("stock_analysis"),
            domain_runner=runner,
            rewriter=lambda state, domains: {},
        )
    )

    result = graph.invoke({"user_message": "分析600519", "run_id": "run-7"})

    assert ran == [BusinessDomain.STOCK_RESEARCH]
    assert list(result["task_results"]) == ["run-7:stock_research"]
    # routing 仍如实记录分类器给出的候选领域。
    assert routing_of(result)["domains"] == ["stock_research"]


def test_stop_arriving_during_the_llm_decision_prevents_dispatch():
    """停止/截止在 **LLM 决策期间**到达时，不得再下发任务。

    回归：节点开头检查一次停止标记后还要花数秒调用 LLM，早先只在开头检查，导致
    这段时间内到达的停止被漏过——任务照常下发，专家产出的 partial 摘要会覆盖
    「已停止本次生成」兜底文案（run_status 仍是 cancelled，但正文不对）。
    """
    from finance_agent.orchestration.graphs.supervisor import CANCELLED_RESPONSE

    # should_dispatch 被调用两次（开头 + LLM 后）：首次放行，第二次报告已停止。
    calls = {"n": 0}

    def should_stop() -> bool:
        calls["n"] += 1
        return calls["n"] > 1

    ran, runner = _runner()
    graph = build_supervisor_graph(
        SupervisorDependencies(
            supervisor_model=make_fake_supervisor_model(),
            classifier=_Classifier("stock_analysis"),
            domain_runner=runner,
            should_stop=should_stop,
            rewriter=lambda state, domains: {},
        )
    )

    result = graph.invoke({"user_message": "分析600519", "run_id": "run-8"})

    assert calls["n"] >= 2, "必须在 LLM 决策后再次检查停止标记"
    assert ran == [], "停止后不得下发任何领域任务"
    assert result["task_results"] == {}
    run = run_of(result)
    assert run["run_status"] == "cancelled"
    assert run["final_response"] == CANCELLED_RESPONSE
