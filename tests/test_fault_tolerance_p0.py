"""第 3–6 项韧性回归：端到端预算、数据源守门、图级容错、停止与可观测性。

对应 rules/langgraph-guides/fault-tolerance.md 的 RetryPolicy / error_handler，
以及"分项超时之外还需要整体上限"的实际缺口。
"""

from __future__ import annotations

import threading
import time

import pytest
from langgraph.errors import NodeError
from langgraph.types import RetryPolicy

from finance_agent.orchestrator.contracts import BusinessDomain, DomainOutcome
from finance_agent.orchestrator.plan_execute import (
    PLAN_CANCELLED_WARNING,
    PLAN_DEADLINE_WARNING,
    run_plan_execute,
)
from finance_agent.orchestrator.supervisor_graph import (
    CANCELLED_RESPONSE,
    CLASSIFICATION_FAILED_RESPONSE,
    SupervisorDependencies,
    build_supervisor_graph,
)
from finance_agent.orchestrator.compliance import BLOCKED_RESPONSE


class _Classifier:
    def __init__(self, intents):
        self._intents = intents

    def classify_intents(self, message, context_summary=""):
        return {
            "intents": [
                {"intent": intent, "query": message, "confidence": 0.99}
                for intent in self._intents
            ],
            "uncertain_intents": [],
            "finance_related": True,
            "classification_error": {},
        }


def _ok(context):
    return DomainOutcome(
        task_id=context.task.task_id,
        domain=context.task.domain,
        status="success",
        summary=f"{context.task.domain.value} 完成。",
    )


# ── 第 3 项：plan_execute 墙钟上限 ──────────────────────────────────────────

def test_plan_execute_stops_at_deadline_and_marks_partial():
    """墙钟上限到点后不再启动新任务，并以 partial 收尾。

    语义边界：上限约束的是"是否下发下一个任务"，无法抢占正在执行的任务
    （同步 in-flight 调用不可中断）。单个任务自身由 provider 超时与节点超时
    约束；这里的职责是防止任务串行累加把整轮拖到无限长。
    """
    from finance_agent.orchestrator.plan_execute import deterministic_planner
    from finance_agent.orchestrator.contracts import BusinessDomain as BD

    domains = [BD.STOCK_RESEARCH, BD.PRODUCT_RESEARCH]
    plan = deterministic_planner({"user_message": "分析并比较"}, domains)
    ran: list[str] = []

    def slow_runner(context):
        ran.append(context.task.domain.value)
        time.sleep(0.3)
        return _ok(context)

    result = run_plan_execute(
        domain_runner=slow_runner,
        initial_plan=plan,
        thread_id="t", run_id="r", customer_id="c",
        conversation_id="conv", user_message="分析并比较",
        max_seconds=0.2,
    )

    assert PLAN_DEADLINE_WARNING in result["warnings"]
    # 第一个任务在执行中无法抢占，但第二个不得被下发。
    assert ran == [BD.STOCK_RESEARCH.value], f"超时后仍下发了任务：{ran}"


def test_plan_execute_stop_callback_skips_remaining_tasks():
    """协作式停止：请求停止后不得再启动新的领域任务。"""
    from finance_agent.orchestrator.plan_execute import deterministic_planner
    from finance_agent.orchestrator.contracts import BusinessDomain as BD

    domains = [BD.STOCK_RESEARCH, BD.PRODUCT_RESEARCH]
    plan = deterministic_planner({"user_message": "分析并比较"}, domains)
    ran: list[str] = []

    def runner(context):
        ran.append(context.task.domain.value)
        return _ok(context)

    result = run_plan_execute(
        domain_runner=runner,
        initial_plan=plan,
        thread_id="t", run_id="r", customer_id="c",
        conversation_id="conv", user_message="分析并比较",
        should_stop=lambda: True,
    )

    assert ran == [], "停止后不得执行任何领域任务"
    assert "plan_cancelled_by_user" in result["warnings"]


# ── 第 5 项：图级 retry + error_handler ─────────────────────────────────────

def test_transient_failure_is_retried_then_succeeds():
    """瞬时故障应被自动重试，而不是立刻降级（默认配置做不到这一点）。"""
    attempts = {"n": 0}

    def flaky(context):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise ConnectionError("transient")
        return _ok(context)

    graph = build_supervisor_graph(
        SupervisorDependencies(classifier=_Classifier(["stock_analysis"]), domain_runner=flaky)
    )
    result = graph.invoke({"user_message": "分析贵州茅台", "run_id": "r1"})

    assert attempts["n"] == 2, "第一次瞬时失败后应重试"
    assert result["run_status"] == "completed"


def test_persistent_failure_degrades_through_error_handler_and_reaches_compliance():
    """重试耗尽后由 error_handler 降级；仍须经合规出口，且不泄露异常细节。"""
    def boom(context):
        raise ValueError("internal detail that must not leak")

    graph = build_supervisor_graph(
        SupervisorDependencies(classifier=_Classifier(["stock_analysis"]), domain_runner=boom)
    )
    result = graph.invoke({"user_message": "分析贵州茅台", "run_id": "r1"})

    # ValueError 默认不可重试，直接进入 handler。
    assert result["run_status"] == "failed"
    assert "node_failed:single_domain:ValueError" in result["warnings"]
    assert "internal detail" not in result["final_response"]
    # 降级输出同样经过合规出口（合规结果一定存在）。
    assert result["compliance"]["action"] in {"passed", "rewritten", "blocked"}


def test_classification_node_failure_reports_unknown_domain():
    """分类节点失败不得静默猜测业务领域。"""
    class _BoomClassifier:
        def classify_intents(self, message, context_summary=""):
            raise RuntimeError("classifier down")

    graph = build_supervisor_graph(SupervisorDependencies(classifier=_BoomClassifier()))
    result = graph.invoke({"user_message": "分析贵州茅台", "run_id": "r1"})

    assert result["run_status"] == "failed"
    assert result["final_response"] == CLASSIFICATION_FAILED_RESPONSE


def test_compliance_node_failure_is_fail_closed():
    """合规出口自身失败必须拦截草稿，绝不放行未经校验的内容。

    必须经真实图执行验证：合规节点失败时最终响应是拦截文案，且草稿被丢弃。
    """
    import finance_agent.orchestrator.compliance as compliance_module
    from finance_agent.orchestrator.compliance import BLOCKED_RESPONSE

    def failing_compliance(*args, **kwargs):
        raise RuntimeError("compliance engine down")

    # 让合规节点依赖的 run_compliance 抛错，验证 error_handler 的兜底行为。
    original = compliance_module.run_compliance
    compliance_module.run_compliance = failing_compliance
    try:
        graph = build_supervisor_graph(
            SupervisorDependencies(
                classifier=_Classifier(["casual_chat"]),
                conversation_runner=lambda state: {
                    "final_response": "该股稳赚不赔。", "status": "success",
                },
            )
        )
        result = graph.invoke({"user_message": "随便聊聊", "run_id": "r1"})
    finally:
        compliance_module.run_compliance = original

    assert result["final_response"] == BLOCKED_RESPONSE
    assert result["compliance"]["action"] == "blocked"
    assert "compliance_unavailable" in result["warnings"]
    # 未校验的草稿绝不能出现在最终响应里。
    assert "稳赚不赔" not in result["final_response"]


# ── 第 6 项：停止标记真正生效 ───────────────────────────────────────────────

def test_should_stop_cancels_single_domain_before_execution():
    """单领域分支也必须在执行前检查停止标记（此前 _is_stopped 是死代码）。"""
    called = {"domain": False}

    def runner(context):
        called["domain"] = True
        return _ok(context)

    graph = build_supervisor_graph(
        SupervisorDependencies(
            classifier=_Classifier(["stock_analysis"]),
            domain_runner=runner,
            should_stop=lambda: True,
        )
    )
    result = graph.invoke({"user_message": "分析贵州茅台", "run_id": "r1"})

    assert called["domain"] is False
    assert result["run_status"] == "cancelled"


def test_orchestrator_stop_check_reads_thread_local_conversation():
    """should_stop 依赖线程本地的 conversation_id 才能查到正确标记。"""
    from finance_agent.orchestrator.orchestrator import AdvisorSystem

    system = object.__new__(AdvisorSystem)
    system._stop_lock = threading.Lock()
    system._stop_requests = {"conv-x": True}
    system._ensure_runtime_state()

    # 未设置上下文时必须安全返回 False（不得抛错）。
    assert system._current_stop_check() is False

    system._stop_context_ref.conversation_id = "conv-x"
    assert system._current_stop_check() is True
    system._stop_context_ref.conversation_id = ""
    assert system._current_stop_check() is False


# ── 第 6 项：静默失败可见 ───────────────────────────────────────────────────

def test_best_effort_records_degradation_count():
    """副作用失败既不抛出，也不静默：必须累计到降级计数。"""
    from finance_agent.orchestrator.orchestrator import AdvisorSystem

    system = object.__new__(AdvisorSystem)

    def boom():
        raise RuntimeError("audit down")

    system._best_effort("audit_complete_run", boom)  # 不得抛出

    assert system.degradation_counts() == {"audit_complete_run": 1}


def test_best_effort_success_does_not_count():
    from finance_agent.orchestrator.orchestrator import AdvisorSystem

    system = object.__new__(AdvisorSystem)
    system._best_effort("audit_complete_run", lambda: None)

    assert system.degradation_counts() == {}


# ── 第 4 项：数据源超时与熔断 ───────────────────────────────────────────────

class _FakeProvider:
    provider_name = "fake"

    def __init__(self, name, *, delay=0.0, error=None, payload=None):
        self.provider_name = name
        self._delay = delay
        self._error = error
        self._payload = payload if payload is not None else {"data": [{"n": name}]}
        self.calls = 0

    def is_available(self):
        return True

    def get_daily(self, *args, **kwargs):
        self.calls += 1
        if self._delay:
            time.sleep(self._delay)
        if self._error is not None:
            raise self._error
        return self._payload

    def get_daily_basic(self, *args, **kwargs):
        self.calls += 1
        if self._delay:
            time.sleep(self._delay)
        if self._error is not None:
            raise self._error
        return self._payload


def _manager(providers, order, **kwargs):
    from finance_agent.data.provider_manager import ProviderManager

    return ProviderManager(providers=providers, order=order, **kwargs)


def test_slow_provider_times_out_and_falls_back():
    """底层不设超时时，ProviderManager 必须强制超时并降级到下一个源。"""
    slow = _FakeProvider("akshare", delay=0.6)
    fast = _FakeProvider("baostock")
    manager = _manager({"akshare": slow, "baostock": fast}, ["akshare", "baostock"],
                       call_timeout=0.15)

    started = time.monotonic()
    result = manager.get_daily("600519")
    elapsed = time.monotonic() - started

    assert result == fast._payload
    assert elapsed < 0.5, f"未在超时后及时降级，耗时 {elapsed:.2f}s"
    assert manager.last_metadata["source"] == "baostock"
    assert "超时" in manager.last_metadata["failures"][0]["error"]


def test_consecutive_failures_open_circuit_and_skip_provider():
    """连续失败的源应被熔断，后续请求不再重复付代价。"""
    broken = _FakeProvider("akshare", error=RuntimeError("down"))
    ok = _FakeProvider("baostock")
    manager = _manager({"akshare": broken, "baostock": ok}, ["akshare", "baostock"],
                       failure_threshold=2, cooldown=60)

    manager.get_daily("600519")  # 第 1 次失败
    manager.get_daily("600519")  # 第 2 次失败 → 达到阈值
    assert broken.calls == 2

    manager.get_daily("600519")  # 熔断中：不应再调用
    assert broken.calls == 2, "熔断期间不得再调用故障源"
    assert manager.last_metadata["circuits_open"] == ["akshare"]


def test_circuit_half_opens_after_cooldown():
    """冷却结束后允许重试一次，成功即恢复。"""
    broken = _FakeProvider("akshare", error=RuntimeError("down"))
    ok = _FakeProvider("baostock")
    manager = _manager({"akshare": broken, "baostock": ok}, ["akshare", "baostock"],
                       failure_threshold=1, cooldown=0.05)

    manager.get_daily("600519")
    assert broken.calls == 1
    time.sleep(0.08)
    broken._error = None  # 恢复
    manager.get_daily("600519")

    assert broken.calls == 2, "冷却结束后应重试一次"
    assert manager.last_metadata["source"] == "akshare"


def test_empty_result_does_not_open_circuit():
    """空结果是"该标的没数据"而非故障，不得熔断（否则会误伤后续标的）。"""
    empty = _FakeProvider("akshare", payload=[])
    ok = _FakeProvider("baostock")
    manager = _manager({"akshare": empty, "baostock": ok}, ["akshare", "baostock"],
                       failure_threshold=1, cooldown=60)

    manager.get_daily("600519")
    manager.get_daily("600519")
    manager.get_daily("600519")

    assert empty.calls == 3, "空结果不应触发熔断"


def test_unsupported_capability_does_not_open_circuit():
    """能力缺口是静态属性，反复出现不是故障，不得熔断。"""
    from finance_agent.data.providers import UnsupportedProviderCapability

    class _NoValuation(_FakeProvider):
        def get_daily_basic(self, *args, **kwargs):
            self.calls += 1
            raise UnsupportedProviderCapability("不支持估值")

    limited = _NoValuation("akshare")
    ok = _FakeProvider("baostock")
    manager = _manager({"akshare": limited, "baostock": ok}, ["akshare", "baostock"],
                       failure_threshold=1, cooldown=60)

    for _ in range(3):
        manager.get_daily_basic("600519")

    assert limited.calls == 3, "能力缺口不应熔断"


# ── 第 3/6 项：SSE 整轮上限不得丢弃已备好的结果 ─────────────────────────────

def _fake_stream_system(handler):
    """构造只带流式所需属性的假系统，并替换 handle_message。"""
    from finance_agent.orchestrator.orchestrator import AdvisorSystem

    system = object.__new__(AdvisorSystem)
    system.handle_message = handler
    return system


def _drain(coro):
    import asyncio

    async def run():
        return [event async for event in coro]

    return asyncio.run(run())


def test_stream_timeout_emits_error_and_stops_heartbeating():
    """整轮上限到点后必须及时给出明确失败，而非无限发送心跳。

    注意：被放弃的工作线程会继续跑完（同步调用不可中断），因此这里断言的是
    **错误事件到达的时刻**，而不是整个 asyncio.run 的耗时——后者会额外等待
    to_thread 的工作线程退出。生产中服务持续运行，泄漏的线程会自行结束；
    其时长由 provider/LLM 各自的分项超时兜住。
    """
    import asyncio

    release = threading.Event()

    def slow_handler(message, chat_history, customer_id, report, conversation_id, resume=False, answers=None):
        release.wait(timeout=5)
        return {"response": "太晚了"}

    system = _fake_stream_system(slow_handler)

    async def run():
        started = time.monotonic()
        error_at = None
        events = []
        async for event in system.handle_message_stream("你好", turn_timeout=0.3):
            events.append(event)
            if event.get("type") == "error":
                error_at = time.monotonic() - started
                break
        return events, error_at

    try:
        events, error_at = asyncio.run(run())
    finally:
        release.set()  # 放行工作线程，避免污染后续测试

    assert error_at is not None, "超时后必须给出 error 事件"
    assert error_at < 3, f"超时后未及时结束流，耗时 {error_at:.2f}s"
    assert events[-1]["type"] == "error"
    assert "超时" in events[-1]["message"]


def test_stream_completed_result_is_not_discarded_as_timeout():
    """任务已完成时，即使已过 deadline 也必须返回结果而不是超时错误。

    否则"算好了但被当成超时丢掉"会让用户白等一轮。
    """
    def fast_handler(message, chat_history, customer_id, report, conversation_id, resume=False, answers=None):
        return {"response": "答案"}

    # turn_timeout 设为极小值：任务会在 deadline 之前就已完成。
    system = _fake_stream_system(fast_handler)
    events = _drain(system.handle_message_stream("你好", turn_timeout=0.001))

    assert events[-1]["type"] == "response"
    assert events[-1]["content"] == "答案"


def test_plan_branch_reports_cancelled_when_stopped():
    """计划分支被停止时必须报 cancelled，与单领域分支语义一致。"""
    graph = build_supervisor_graph(
        SupervisorDependencies(
            classifier=_Classifier(["stock_analysis", "product_analysis"]),
            domain_runner=_ok,
            should_stop=lambda: True,
        )
    )
    result = graph.invoke({"user_message": "分析贵州茅台并比较基金", "run_id": "r1"})

    assert result["run_status"] == "cancelled"
    assert PLAN_CANCELLED_WARNING in result["warnings"]
