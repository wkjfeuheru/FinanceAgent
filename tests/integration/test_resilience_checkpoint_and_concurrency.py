"""P0 韧性回归：根图接 checkpointer、/api/chat 不阻塞 event loop、会话级并发。

这三项对应 LangGraph 官方 fault-tolerance 指南
（https://docs.langchain.com/oss/python/langgraph/fault-tolerance）之外的可用性缺口：
- 图未接 checkpointer → 运行状态不落库，崩溃后不可恢复；
- 同步端点直接在协程里跑阻塞编排 → 占住整个 event loop；
- 整轮全局锁 → 一个慢请求串行化所有会话。
"""

from __future__ import annotations

import asyncio
import threading
import time

from langgraph.checkpoint.memory import InMemorySaver

from finance_agent.api import dependencies as deps
from finance_agent.api.routers import chat as r
from finance_agent.application.advisor import AdvisorSystem
from finance_agent.orchestration.graphs.supervisor import (
    SupervisorDependencies,
    build_supervisor_graph,
    run_of,
)


class _FakeClassifier:
    def classify_intents(self, message: str, context_summary: str = "") -> dict:
        return {
            "intents": [{"intent": "casual_chat", "query": message, "confidence": 0.99}],
            "uncertain_intents": [],
            "finance_related": True,
            "classification_error": {},
        }


def _conversation_runner(state):
    return {"final_response": "你好。", "status": "success"}


# ── 修复 1：根图接 checkpointer ──────────────────────────────────────────────

def test_root_graph_persists_state_by_thread_id():
    """带 checkpointer 时，终态必须能按 thread_id 读回（崩溃后可续的前提）。"""
    checkpointer = InMemorySaver()
    graph = build_supervisor_graph(
        SupervisorDependencies(
            classifier=_FakeClassifier(),
            conversation_runner=_conversation_runner,
        ),
        checkpointer=checkpointer,
    )
    config = {"configurable": {"thread_id": "v1:CUST1:conv-1"}}
    result = graph.invoke({"user_message": "你好", "run_id": "run-1"}, config)

    assert run_of(result)["final_response"]
    snapshot = graph.get_state(config)
    assert run_of(snapshot.values)["final_response"] == run_of(result)["final_response"]


def test_root_graph_without_checkpointer_still_runs():
    """未注入 checkpointer（测试/单次调用）时必须照常执行，配置被忽略。"""
    graph = build_supervisor_graph(
        SupervisorDependencies(
            classifier=_FakeClassifier(),
            conversation_runner=_conversation_runner,
        )
    )
    result = graph.invoke(
        {"user_message": "你好", "run_id": "run-2"},
        {"configurable": {"thread_id": "v1:CUST1:conv-2"}},
    )
    assert run_of(result)["final_response"]


def test_handle_message_passes_thread_id_in_config(monkeypatch):
    """thread_id 必须出现在 invoke 的 config 里；只在 state 里传对 checkpoint 无效。"""
    from finance_agent.orchestration.runtime.thread_key import build_thread_id

    system = object.__new__(AdvisorSystem)
    system._stop_lock = threading.Lock()
    system._stop_requests = {}
    system._active_runs = {}
    system._progress_lock = threading.Lock()
    system._progress_callbacks = {}
    system._trace_lock = threading.Lock()
    system._trace_sequences = {}
    system._progress_context = type("Ctx", (), {"callback": None})()
    system.memory = type("M", (), {
        "window_size": 10,
        "load_context": lambda self, c, conv, fb: {
            "profile": {}, "context_text": "", "sliding_window": [],
        },
        "append_window_message": lambda *a, **k: None,
        "update_profile_from_result": lambda *a, **k: None,
    })()
    system.audit = type("A", (), {"create_run": lambda *a, **k: None})()
    system.get_checkpoint_conversation_messages = lambda *a, **k: []
    system._emit_progress = lambda *a, **k: None
    system._trace_agent = lambda *a, **k: None
    system._persist = lambda *a, **k: None

    captured: dict = {}

    class _Supervisor:
        def invoke(self, state, config=None):
            captured["state"] = state
            captured["config"] = config
            # 新契约：每轮派生状态收在 run 单键下，扇出结论走 task_results。
            return {"run": {"final_response": "ok", "run_status": "completed"}, "task_results": {}}

    system.supervisor = _Supervisor()

    system.handle_message("你好", conversation_id="conv-cfg")

    config = captured["config"]
    assert config["configurable"]["thread_id"] == build_thread_id("CUST001", "conv-cfg")
    # 第 3 项：ORCHESTRATION_GRAPH_STEPS 必须真正接到图上，而非只写在配置里。
    from finance_agent.infrastructure.settings import ORCHESTRATION_GRAPH_STEPS

    assert config["recursion_limit"] == ORCHESTRATION_GRAPH_STEPS


# ── 修复 2a：/api/chat 不得阻塞 event loop ──────────────────────────────────

class _FakeRequest:
    def __init__(self):
        self.headers = {"Authorization": "Bearer good-token"}


class _ChatRequest:
    def __init__(self, message="你好", conversation_id=""):
        self.message = message
        self.conversation_id = conversation_id
        self.chat_history = []
        self.customer_id = ""
        self.resume = False
        self.answers = {}


def _auth_store(monkeypatch):
    class _Store:
        def verify_token(self, token):
            return "CUST1" if token == "good-token" else None

    monkeypatch.setattr(deps, "get_user_store", lambda: _Store())


def test_chat_runs_handler_off_the_event_loop_thread(monkeypatch):
    """handle_message 同步阻塞，必须交给工作线程执行。"""
    _auth_store(monkeypatch)
    caller_thread = threading.get_ident()
    seen: dict = {}

    class _System:
        def handle_message(self, **kwargs):
            seen["thread"] = threading.get_ident()
            return {"response": "ok", "conversation_id": "c1"}

    monkeypatch.setattr(r, "get_system", lambda: _System())

    asyncio.run(r.chat(_ChatRequest(conversation_id=""), _FakeRequest()))

    assert seen["thread"] != caller_thread, "阻塞调用必须卸载到工作线程"


def test_chat_does_not_block_concurrent_event_loop_work(monkeypatch):
    """编排阻塞期间，event loop 仍必须能调度其它协程（旧实现会整段占死）。"""
    _auth_store(monkeypatch)
    release = threading.Event()
    handler_entered = threading.Event()

    class _System:
        def handle_message(self, **kwargs):
            handler_entered.set()
            release.wait(timeout=3)
            return {"response": "ok", "conversation_id": "c1"}

    monkeypatch.setattr(r, "get_system", lambda: _System())

    async def probe():
        return "health-ok"

    async def scenario():
        chat_task = asyncio.create_task(r.chat(_ChatRequest(conversation_id=""), _FakeRequest()))
        # 等编排进入阻塞点。
        for _ in range(500):
            if handler_entered.is_set():
                break
            await asyncio.sleep(0.01)
        assert handler_entered.is_set()
        # 若编排占用 event loop，此刻 chat_task 早已跑完（说明同步阻塞了循环）。
        assert not chat_task.done(), "编排不得在 event loop 线程内同步跑完"
        # 编排仍在阻塞时，另一个请求必须能被及时调度。
        other = await asyncio.wait_for(probe(), timeout=1)
        release.set()
        await asyncio.wait_for(chat_task, timeout=5)
        return other

    assert asyncio.run(scenario()) == "health-ok"


# ── 修复 2b：会话级锁 ────────────────────────────────────────────────────────

def test_conversation_guard_serializes_same_conversation():
    """同一会话的两次轮次必须互斥（进度回调/记忆窗口按会话定位）。"""
    system = object.__new__(AdvisorSystem)
    order: list[str] = []
    first_in = threading.Event()
    release_first = threading.Event()

    def first():
        with system._conversation_guard("conv-1"):
            order.append("first-in")
            first_in.set()
            release_first.wait(timeout=5)
            order.append("first-out")

    def second():
        first_in.wait(timeout=5)
        with system._conversation_guard("conv-1"):
            order.append("second-in")

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for thread in threads:
        thread.start()
    assert first_in.wait(timeout=5)
    time.sleep(0.05)
    assert order == ["first-in"], "第二个轮次必须等第一个退出临界区"
    release_first.set()
    for thread in threads:
        thread.join(timeout=5)

    assert order == ["first-in", "first-out", "second-in"]


def test_conversation_guard_allows_different_conversations_in_parallel():
    """不同会话之间不得互相阻塞（旧实现会退化成全局串行）。"""
    system = object.__new__(AdvisorSystem)
    both_in = threading.Barrier(2, timeout=5)

    def worker(conversation_id):
        with system._conversation_guard(conversation_id):
            both_in.wait()

    threads = [
        threading.Thread(target=worker, args=("conv-a",)),
        threading.Thread(target=worker, args=("conv-b",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads), "两会话必须能同时进入临界区"


def test_conversation_guard_cleans_up_registry():
    """临界区退出后注册表不得泄漏条目。"""
    system = object.__new__(AdvisorSystem)
    with system._conversation_guard("conv-x"):
        pass
    assert not system.__dict__.get("_conversation_locks")


# ── 修复 1 的回归：per-turn 键不得跨轮次泄漏 ─────────────────────────────────

class _SwitchableClassifier:
    """按消息内容返回不同领域，用于模拟同一会话里不同类型的连续提问。"""

    def classify_intents(self, message: str, context_summary: str = "") -> dict:
        intent = "casual_chat" if "规则" in message else "stock_analysis"
        return {
            "intents": [{"intent": intent, "query": message, "confidence": 0.99}],
            "uncertain_intents": [],
            "finance_related": True,
            "classification_error": {},
        }


def test_trusted_content_does_not_leak_across_turns():
    """上一轮 FAQ 命中的 trusted_content 不得让本轮分析跳过合规改写。"""
    from finance_agent.orchestration.contracts import BusinessDomain, DomainOutcome

    checkpointer = InMemorySaver()

    def domain_runner(context):
        return DomainOutcome(
            task_id=context.task.task_id,
            domain=BusinessDomain.STOCK_RESEARCH,
            status="success",
            summary="该股稳赚不赔，必涨。",
        )

    graph = build_supervisor_graph(
        SupervisorDependencies(
            classifier=_SwitchableClassifier(),
            conversation_runner=lambda state: {
                "final_response": "定投规则说明。", "status": "success", "cited_faq": True,
            },
            domain_runner=domain_runner,
        ),
        checkpointer=checkpointer,
    )
    config = {"configurable": {"thread_id": "v1:CUST1:conv-leak"}}

    first = graph.invoke({"user_message": "定投规则是什么", "run_id": "r1"}, config)
    assert run_of(first)["trusted_content"] is True  # 本轮确实是受信内容

    second = graph.invoke({"user_message": "分析贵州茅台", "run_id": "r2"}, config)

    # 风险话术必须被处理掉（改写或拦截），绝不能因残留的 trusted_content 放行。
    assert run_of(second)["trusted_content"] is False
    assert "稳赚不赔" not in run_of(second)["final_response"]
    assert run_of(second)["compliance"]["action"] in {"rewritten", "blocked"}


def test_warnings_do_not_leak_across_turns():
    """澄清成功分支不写 warnings；不得残留上一轮的提示。

    新契约下每轮派生状态收在 ``run`` 单键、由 ``classify`` 整键覆盖，因此
    "上一轮的提示"经 ``run.warnings`` 注入（旧实现是顶层 ``warnings``）。
    """
    checkpointer = InMemorySaver()
    graph = build_supervisor_graph(
        SupervisorDependencies(
            classifier=_FakeClassifier(),
            conversation_runner=_conversation_runner,
        ),
        checkpointer=checkpointer,
    )
    config = {"configurable": {"thread_id": "v1:CUST1:conv-warn"}}

    graph.invoke(
        {"user_message": "你好", "run_id": "w1", "run": {"warnings": ["stale"]}}, config,
    )
    second = graph.invoke({"user_message": "你好", "run_id": "w2"}, config)

    assert "stale" not in run_of(second)["warnings"]


# ── 修复 2 的并发安全：共享存储的懒初始化必须只跑一次 ───────────────────────

def test_business_store_applies_schema_only_once_under_concurrency():
    """放开并发后，懒建表必须互斥：并发进入只能执行一次 DDL。"""
    from finance_agent.infrastructure.persistence.postgres.business_store import PostgresBusinessStore

    calls = {"n": 0}
    calls_lock = threading.Lock()

    class _Cursor:
        def execute(self, sql):
            with calls_lock:
                calls["n"] += 1

        def close(self):
            pass

    class _Conn:
        def cursor(self):
            return _Cursor()

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    store = PostgresBusinessStore(lambda: _Conn())
    start = threading.Barrier(8, timeout=5)

    def worker():
        start.wait()
        store._ensure_schema()

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    # 全部结构迁移只应执行一轮（数量以唯一迁移序列为准，不再硬编码）。
    from finance_agent.infrastructure.persistence.postgres.migrations import MIGRATIONS

    assert calls["n"] == len(MIGRATIONS), (
        f"建表被执行了 {calls['n']} 次，说明锁未生效"
    )


def test_audit_store_setup_schema_only_once_under_concurrency():
    """审计存储的懒建表同理：并发下只 setup 一次。"""
    from finance_agent.infrastructure.persistence.postgres.audit_repository import PostgresAuditStore

    setup_calls = {"n": 0}
    setup_lock = threading.Lock()

    class _Repo:
        def setup_schema(self):
            with setup_lock:
                setup_calls["n"] += 1
                time.sleep(0.05)  # 放大竞争窗口

    store = object.__new__(PostgresAuditStore)
    store._repository = _Repo()
    store._research_repository = None
    store._schema_ready = False
    store._schema_lock = threading.Lock()

    start = threading.Barrier(8, timeout=5)

    def worker():
        start.wait()
        store._ensure_schema()

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert setup_calls["n"] == 1, f"setup_schema 被执行了 {setup_calls['n']} 次"
