"""第 3–6 项韧性回归：端到端预算、数据源守门、图级容错、停止与可观测性。

对应 LangGraph 官方 fault-tolerance 指南
（https://docs.langchain.com/oss/python/langgraph/fault-tolerance）的 RetryPolicy /
error_handler，以及"分项超时之外还需要整体上限"的实际缺口。

迁移说明（旧 ``plan_execute`` 模块已删除，无替代实现）：

- ``run_plan_execute`` / ``deterministic_planner`` / ``PlanRunResult`` 随模块删除。
  它们的**串行下发**语义（"上限约束的是是否下发下一个任务"）在新根图里不存在：
  领域任务由 ``scope_tasks`` 一次 ``Send`` 并行扇出，截止因此落在**下发前**与
  ``converge`` 两处统一检查。对应的行为断言已在新图上重新表达（见下方两节）。
- ``PLAN_CANCELLED_WARNING`` / ``PLAN_DEADLINE_WARNING`` 改名并移入
  ``orchestration.contracts``：``RUN_CANCELLED_WARNING`` / ``TURN_DEADLINE_WARNING``。
- 每轮状态从散落的顶层键收进单个 ``run`` 键（用 ``run_of`` 读取）；
  ``single_domain`` 节点删除，单/多领域走同一条扇出路径。
"""

from __future__ import annotations

import threading
import time

from finance_agent.orchestration.budgets import RunBudgets
from tests.conftest import make_fake_supervisor_model
from finance_agent.orchestration.contracts import (
    RUN_CANCELLED_WARNING,
    TURN_DEADLINE_WARNING,
    BusinessDomain,
    DomainOutcome,
)
from finance_agent.orchestration.graphs.supervisor import (
    CANCELLED_RESPONSE,
    CLASSIFICATION_FAILED_RESPONSE,
    DEADLINE_FALLBACK_RESPONSE,
    SupervisorDependencies,
    build_supervisor_graph,
    run_of,
    task_id_of,
)
from finance_agent.orchestration.graphs.compliance import BLOCKED_RESPONSE


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


def _graph(*, intents, runner=None, conversation_runner=None, should_stop=None,
           budgets=None, rewriter=None):
    """构造被测根图；默认注入空改写器，避免默认改写器（惰性构造 INTENT_MODEL）
    把外部依赖带进这些韧性测试。"""
    return build_supervisor_graph(
        SupervisorDependencies(
            supervisor_model=make_fake_supervisor_model(),
            classifier=_Classifier(intents),
            domain_runner=runner,
            conversation_runner=conversation_runner,
            should_stop=should_stop,
            budgets=budgets,
            rewriter=rewriter if rewriter is not None else (lambda state, domains: {}),
        )
    )


# ── 第 3 项：整轮墙钟上限（原 plan_execute 串行下发语义已删除）──────────────


def test_turn_deadline_before_dispatch_skips_domain_work_and_degrades_honestly():
    """整轮上限到点后一个领域任务都不得启动，并以 partial + 明确原因收尾。

    旧 ``run_plan_execute`` 串行下发，"到点后不再下发**下一个**任务"（正在执行的
    任务不可抢占）。新根图一次 ``Send`` 并行扇出全部领域，没有"下一个任务"，因此
    截止检查落在下发前（``route_after_scope``）：到点即整体不下发，已完成结论（若有）
    保留。这里验证不启动执行、降级原因与兜底文案都如实。
    """
    ran: list[str] = []

    def runner(context):
        ran.append(context.task.domain.value)
        return _ok(context)

    graph = _graph(
        intents=["stock_analysis", "product_analysis"],
        runner=runner,
        budgets=RunBudgets(turn_deadline=0.0001),
    )
    result = graph.invoke({"user_message": "分析并比较", "run_id": "r1"})
    run = run_of(result)

    assert ran == [], f"整轮已超时，仍下发了领域任务：{ran}"
    assert TURN_DEADLINE_WARNING in run["degradations"]
    assert run["run_status"] == "partial"
    assert run["final_response"] == DEADLINE_FALLBACK_RESPONSE


# 已删除：``test_plan_execute_stops_at_deadline_and_marks_partial`` 与
# ``test_plan_execute_stop_callback_skips_remaining_tasks``。
# 两者直接构造 ``deterministic_planner`` 的计划并断言 ``run_plan_execute`` 的
# **串行**下发顺序（"第二个任务不得被下发"）；该模块与其计划契约已删除，
# 串行顺序本身不再是产品语义——领域下发是并行的。行为意图改由上方
# （截止前不下发）与下方停止测试（停止后不下发）在新图上覆盖。


# ── 第 5 项：图级 retry + error_handler ─────────────────────────────────────


def test_transient_failure_is_retried_then_succeeds():
    """瞬时故障应被自动重试，而不是立刻降级（默认配置做不到这一点）。

    验证对象是**图级 RetryPolicy**：这里用会话节点，因为领域执行器的异常现在被
    ``domain_worker`` 收敛为该领域的 failed 结论（单域失败不得打断整轮），不会再
    冒泡到重试策略；异常会冒泡的节点才谈得上"重试"。
    """
    attempts = {"n": 0}

    def flaky_conversation(state):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise ConnectionError("transient")
        return {"final_response": "你好，我是投顾助手。", "status": "success"}

    graph = _graph(intents=["casual_chat"], conversation_runner=flaky_conversation)
    result = graph.invoke({"user_message": "你好", "run_id": "r1"})

    assert attempts["n"] == 2, "第一次瞬时失败后应重试"
    assert run_of(result)["run_status"] == "completed"


def test_persistent_node_failure_degrades_through_error_handler_and_reaches_compliance():
    """重试耗尽后由 error_handler 降级；仍须经合规出口，且不泄露异常细节。

    被验证的节点从 ``single_domain`` 换成 ``conversation``：领域执行器的异常现在由
    ``domain_worker`` 收敛为 failed 结论（见下一个测试），只有节点自身抛出的异常才
    会走 error_handler。
    """

    def boom(state):
        raise ValueError("internal detail that must not leak")

    graph = _graph(intents=["casual_chat"], conversation_runner=boom)
    result = graph.invoke({"user_message": "你好", "run_id": "r1"})
    run = run_of(result)

    # ValueError 默认不可重试，直接进入 handler。
    assert run["run_status"] == "failed"
    assert "node_failed:conversation:ValueError" in run["degradations"]
    assert "internal detail" not in run["final_response"]
    # 降级输出同样经过合规出口（合规结果一定存在）。
    assert run["compliance"]["action"] in {"passed", "rewritten", "blocked", "audited"}


def test_persistent_domain_failure_degrades_and_reaches_compliance():
    """领域执行器持续失败：该域如实降级为 failed，且仍经合规出口、不泄露异常细节。"""
    def boom(context):
        raise ValueError("internal detail that must not leak")

    graph = _graph(intents=["stock_analysis"], runner=boom)
    result = graph.invoke({"user_message": "分析贵州茅台", "run_id": "r1"})
    run = run_of(result)

    assert run["run_status"] == "failed"
    assert "domain_runner_failed:stock_research" in run["warnings"]
    assert "internal detail" not in run["final_response"]
    assert run["compliance"]["action"] in {"passed", "rewritten", "blocked", "audited"}


def test_failing_domain_does_not_abort_sibling_domains():
    """跨领域扇出下，一个领域失败不得让其它领域的结果丢失（并行隔离）。

    旧做法在单个节点里串行执行计划：任何一步异常都要整轮重跑。现在每个领域任务是
    独立 superstep，失败只把该领域标为 failed，成功领域照常进入汇合与合规。
    """
    def only_product_fails(context):
        if context.task.domain is BusinessDomain.PRODUCT_RESEARCH:
            raise RuntimeError("product provider down")
        return _ok(context)

    graph = _graph(
        intents=["stock_analysis", "product_analysis"],
        runner=only_product_fails,
    )
    result = graph.invoke({"user_message": "分析贵州茅台并比较基金产品", "run_id": "r1"})
    run = run_of(result)

    stock_id = task_id_of("r1", BusinessDomain.STOCK_RESEARCH)
    product_id = task_id_of("r1", BusinessDomain.PRODUCT_RESEARCH)
    assert set(result["task_results"]) == {stock_id, product_id}
    assert result["task_results"][stock_id]["status"] == "success"
    assert result["task_results"][product_id]["status"] == "failed"
    # 失败域的降级可观测，且只把整轮降为 partial（不是 failed）：另一域仍有结论。
    assert "domain_runner_failed:product_research" in run["warnings"]
    assert run["run_status"] == "partial"


def test_classification_node_failure_reports_unknown_domain():
    """分类节点失败不得静默猜测业务领域。"""
    class _BoomClassifier:
        def classify_intents(self, message, context_summary=""):
            raise RuntimeError("classifier down")

    graph = build_supervisor_graph(SupervisorDependencies(
            supervisor_model=make_fake_supervisor_model(),classifier=_BoomClassifier()))
    result = graph.invoke({"user_message": "分析贵州茅台", "run_id": "r1"})

    assert run_of(result)["run_status"] == "failed"
    assert run_of(result)["final_response"] == CLASSIFICATION_FAILED_RESPONSE


def test_compliance_node_failure_is_fail_closed():
    """合规出口自身失败必须拦截草稿，绝不放行未经校验的内容。

    必须经真实图执行验证：合规节点失败时最终响应是拦截文案，且草稿被丢弃。
    """
    import finance_agent.orchestration.graphs.compliance as compliance_module

    def failing_compliance(*args, **kwargs):
        raise RuntimeError("compliance engine down")

    # 让合规节点依赖的 run_compliance 抛错，验证 error_handler 的兜底行为。
    original = compliance_module.run_compliance
    compliance_module.run_compliance = failing_compliance
    try:
        graph = _graph(
            intents=["casual_chat"],
            conversation_runner=lambda state: {
                "final_response": "该股稳赚不赔。", "status": "success",
            },
        )
        result = graph.invoke({"user_message": "随便聊聊", "run_id": "r1"})
    finally:
        compliance_module.run_compliance = original

    run = run_of(result)
    assert run["final_response"] == BLOCKED_RESPONSE
    assert run["compliance"]["action"] == "blocked"
    assert "compliance_unavailable" in run["degradations"]
    # 未校验的草稿绝不能出现在最终响应里。
    assert "稳赚不赔" not in run["final_response"]


# ── 第 6 项：停止标记真正生效 ───────────────────────────────────────────────


def test_should_stop_cancels_domain_before_execution():
    """已请求停止时，领域任务在执行前就被拦下，并以 cancelled 收尾。"""
    called = {"domain": False}

    def runner(context):
        called["domain"] = True
        return _ok(context)

    graph = _graph(
        intents=["stock_analysis"],
        runner=runner,
        should_stop=lambda: True,
    )
    result = graph.invoke({"user_message": "分析贵州茅台", "run_id": "r1"})
    run = run_of(result)

    assert called["domain"] is False
    assert run["run_status"] == "cancelled"
    assert RUN_CANCELLED_WARNING in run["degradations"]
    assert run["final_response"] == CANCELLED_RESPONSE


def test_multi_domain_stop_reports_cancelled_with_same_semantics():
    """多领域扇出被停止时同样报 cancelled（单/多领域共用同一条路径）。"""
    ran: list[str] = []

    def runner(context):
        ran.append(context.task.domain.value)
        return _ok(context)

    graph = _graph(
        intents=["stock_analysis", "product_analysis"],
        runner=runner,
        should_stop=lambda: True,
    )
    result = graph.invoke({"user_message": "分析贵州茅台并比较基金", "run_id": "r1"})
    run = run_of(result)

    assert ran == [], "停止后不得执行任何领域任务"
    assert run["run_status"] == "cancelled"
    assert RUN_CANCELLED_WARNING in run["degradations"]


def test_orchestrator_stop_check_reads_thread_local_conversation():
    """should_stop 依赖线程本地的 conversation_id 才能查到正确标记。"""
    from finance_agent.application.advisor import AdvisorSystem

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
    from finance_agent.application.advisor import AdvisorSystem

    system = object.__new__(AdvisorSystem)

    def boom():
        raise RuntimeError("audit down")

    system._best_effort("audit_complete_run", boom)  # 不得抛出

    assert system.degradation_counts() == {"audit_complete_run": 1}


def test_best_effort_success_does_not_count():
    from finance_agent.application.advisor import AdvisorSystem

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
    from finance_agent.infrastructure.market_data.provider_manager import ProviderManager

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
    from finance_agent.infrastructure.market_data.providers import UnsupportedProviderCapability

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
    from finance_agent.application.advisor import AdvisorSystem

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
