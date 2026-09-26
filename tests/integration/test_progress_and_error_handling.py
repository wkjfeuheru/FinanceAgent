"""异常不泄露与进度送达的回归护栏（面向专家子图与编排入口）。

旧 ``orchestrator.domains.stock`` 领域图与 ``invoke_stock`` 已删除。专家故障
不再回传原始异常：``build_expert_graph`` 的 agent 节点捕获模型/图故障，只给
固定不可用文案。进度送达仍由 ``AdvisorSystem._emit_progress`` 承载。
"""

from __future__ import annotations

import threading

from finance_agent.orchestration.contracts import BusinessDomain, DomainTaskContext, PlanTask
from finance_agent.orchestration.experts.base import build_expert_graph
from finance_agent.domains.research.expert import stock_tools
from finance_agent.application.advisor import AdvisorSystem


def _context(message: str) -> DomainTaskContext:
    return DomainTaskContext(
        task=PlanTask(
            task_id="single:run-1:stock_research",
            domain=BusinessDomain.STOCK_RESEARCH,
            goal=message,
            instruction=message,
            expected_output="domain_outcome",
        ),
        thread_id="v1:CUST1:conv-1",
        customer_id="CUST1",
        conversation_id="conv-1",
        user_message=message,
    )


class _ExplodingModel:
    """模型调用即抛异常：模拟内部/模型故障。"""

    def bind_tools(self, tools, **kwargs):
        return self

    def invoke(self, *args, **kwargs):
        raise RuntimeError("DB_PASSWORD=secret / internal detail")


def test_expert_failure_does_not_leak_internal_exception():
    """专家内部异常只给固定文案，原始异常文本（含敏感细节）不得外泄。"""
    graph = build_expert_graph(
        BusinessDomain.STOCK_RESEARCH,
        tools=stock_tools(),
        system_prompt="json",
        max_steps=4,
        model=_ExplodingModel(),
        unavailable_text="该领域数据暂时无法生成，请稍后重试。",
    )

    outcome = graph.invoke({"context": _context("分析600519")})["domain_outcome"]

    assert outcome.status == "failed"
    assert "DB_PASSWORD" not in outcome.summary
    assert "secret" not in outcome.summary
    assert "internal detail" not in outcome.summary
    assert "暂不可用" not in outcome.summary  # 用的是本域固定文案
    assert "无法生成" in outcome.summary
    assert outcome.limitations == ["expert_unavailable"]


def test_expert_failure_default_text_does_not_leak():
    """未指定 unavailable_text 时使用通用兜底文案，仍不泄露异常。"""
    graph = build_expert_graph(
        BusinessDomain.STOCK_RESEARCH,
        tools=stock_tools(),
        system_prompt="json",
        max_steps=4,
        model=_ExplodingModel(),
    )

    outcome = graph.invoke({"context": _context("分析600519")})["domain_outcome"]

    assert "DB_PASSWORD" not in outcome.summary
    assert "internal detail" not in outcome.summary
    assert outcome.summary


def test_emit_progress_routes_by_conversation_id_from_worker_thread():
    """专家进度在工作线程产生，必须按 conversation_id 送达主线程注册的回调。"""
    system = object.__new__(AdvisorSystem)
    system._progress_lock = threading.Lock()
    system._progress_callbacks = {}
    system._progress_context = threading.local()

    events: list[tuple[str, str]] = []
    system._progress_callbacks["conv-1"] = lambda stage, msg: events.append((stage, msg))

    def worker():
        system._emit_progress("stock_analysis", "正在执行", "conv-1")

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()

    assert events == [("stock_analysis", "正在执行")]


def test_emit_progress_absent_callback_does_not_raise():
    system = object.__new__(AdvisorSystem)
    system._progress_lock = threading.Lock()
    system._progress_callbacks = {}
    system._progress_context = threading.local()

    system._emit_progress("manager", "无回调", "conv-none")
