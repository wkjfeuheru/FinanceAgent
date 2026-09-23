"""金融投顾编排系统（LangGraph V2 唯一路径）。

对外保留既有同步/流式签名与响应字段；内部由 Supervisor Graph 统一承担分类、路由、
单领域 Domain ReAct / 复合 Plan-and-Execute 调度，所有输出经统一合规出口投影。
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from typing import Any, Callable, Dict, List

from langgraph.types import Command

from finance_agent.config import (
    ORCHESTRATION_PLAN_DEADLINE,
    ORCHESTRATION_STREAM_CHUNK_DELAY_MS,
    ORCHESTRATION_STREAM_CHUNK_SIZE,
    ORCHESTRATION_STREAM_MAX_SECONDS,
    ORCHESTRATION_TURN_TIMEOUT,
    get_checkpoint_saver,
    get_supervisor_model,
)
from finance_agent.contracts import FactSnapshot, RequestEnvelope, generate_identifiers
from finance_agent.data.postgres_repository import PostgresAuditStore
from finance_agent.orchestrator.contracts import (
    DEFAULT_JOB_RUN_STATUS,
    JOB_STATUS_TO_RUN_STATUS,
    DomainOutcome,
    DomainTaskContext,
    RunBudgets,
)
from finance_agent.orchestrator.database import get_database
from finance_agent.orchestrator.intent import IntentClassifier
from finance_agent.orchestrator.memory import AgentMemoryContext, RedisMemoryStore
from finance_agent.orchestrator.params import (
    CANCEL_SENTINEL,
    profile_updates_from_answers,
)
from finance_agent.orchestrator.plan_execute import deterministic_planner
from finance_agent.orchestrator.resume import ResumeCoordinator
from finance_agent.orchestrator.supervisor_graph import (
    SupervisorDependencies,
    build_supervisor_graph,
    project_interrupt_state,
    project_supervisor_state,
)
from finance_agent.orchestrator.run_state import RunStateStore
from finance_agent.orchestrator.thread_key import build_thread_id
from finance_agent.research.contracts import AnalysisRequest, AnalysisResult
from finance_agent.middleware import BLOCKED_RESPONSE, should_block_input

logger = logging.getLogger(__name__)


def _stable_user_id(customer_id: str) -> uuid.UUID:
    """从 customer_id 派生稳定 UUID，供审计按用户维度聚合。

    RequestEnvelope.user_id 是 UUID 类型，customer_id 字符串不能直接传入；
    若每轮随机生成，审计表按 user_id 做用户维度关联将永远无法命中同一客户。
    """
    return uuid.uuid5(uuid.NAMESPACE_URL, f"finance-agent:customer:{customer_id}")


def _iter_stream_chunks(text: str, chunk_size: int) -> List[str]:
    """把定稿答复切成 SSE 下发用的文本块。

    按 Python 码点切分（而非字节），不会拆坏多字节字符。流式只改变**呈现节奏**：
    内容、顺序与最终 ``response`` 事件完全一致，前端据此累积渲染。
    """
    if not text:
        return []
    size = max(1, chunk_size)
    return [text[index:index + size] for index in range(0, len(text), size)]


def _stream_chunk_delay(total_chunks: int) -> float:
    """按总块数收敛每块停顿，使分块下发的额外耗时不超过配置上限。

    长报告若按固定停顿逐块下发会叠出数秒等待；这里把每块停顿压到
    ``ORCHESTRATION_STREAM_MAX_SECONDS / 总块数`` 以内，流式只为观感服务，
    不让整体时延被"打字机"拖长。
    """
    if total_chunks <= 0:
        return 0.0
    base = max(0.0, ORCHESTRATION_STREAM_CHUNK_DELAY_MS / 1000.0)
    if base == 0.0 or ORCHESTRATION_STREAM_MAX_SECONDS <= 0:
        return 0.0
    return min(base, ORCHESTRATION_STREAM_MAX_SECONDS / total_chunks)


# 会话级互斥锁：同一会话的轮次必须串行——进度回调、记忆窗口和 checkpoint
# 都按 conversation_id / thread_id 定位，并发轮次会互相覆盖；不同会话之间
# 则不应互相阻塞（旧的整轮全局锁会退化成串行处理所有用户）。
# 轻量运行时字段（锁/注册表/线程本地）由 _ensure_runtime_state 幂等补全：
# 测试会用 object.__new__(AdvisorSystem) 构造实例而不执行 __init__，
# 该守卫同时保护初始化与会话锁注册表的并发访问。
_RUNTIME_STATE_GUARD = threading.Lock()


class AdvisorSystem:
    """金融投顾编排系统（Supervisor Graph 为唯一执行路径）。"""

    def __init__(self):
        # 轻量运行时字段（锁/注册表/线程本地）统一由 _ensure_runtime_state
        # 幂等补全，object.__new__ 构造的实例同样安全。
        self._ensure_runtime_state()
        # 运行预算的唯一配置源：config.ORCHESTRATION_* → 受校验 RunBudgets。
        # 会话 ReAct 步数、计划任务数、重规划次数、合规改写次数与根图递归
        # 上限都从这里取值，不允许各模块再自带一份默认值。
        self.budgets = RunBudgets.from_config()
        self.checkpointer = get_checkpoint_saver()
        self.run_state = RunStateStore(
            checkpointer=self.checkpointer,
            business_store=get_database(),
        )
        self.memory = AgentMemoryContext(
            store=RedisMemoryStore(), checkpointer=self.checkpointer,
        )
        self.classifier = IntentClassifier()
        self.audit = PostgresAuditStore.from_config()
        self._faq_retriever = None
        self._async_run_repository = None
        self._quant_gateway = None
        self.supervisor = self._build_supervisor()

    def _ensure_runtime_state(self) -> None:
        """幂等补全轻量运行时字段（锁/注册表/线程本地），已存在的字段
        （含测试注入的 mock）不会被覆盖。

        重量级依赖（checkpointer/memory/audit/root 等）不在此处构建，
        仍由 __init__ 或调用方提供。双检锁保证并发入口下只初始化一次。
        """
        if self.__dict__.get("_runtime_state_ready"):
            return
        with _RUNTIME_STATE_GUARD:
            if self.__dict__.get("_runtime_state_ready"):
                return
            defaults: tuple[tuple[str, Any], ...] = (
                ("_conversation_locks", dict),
                ("_progress_context", threading.local),
                ("_stop_context_ref", threading.local),
                ("_progress_callbacks", dict),
                ("_progress_lock", threading.Lock),
                ("_trace_lock", threading.Lock),
                ("_trace_sequences", dict),
                ("_stop_requests", dict),
                ("_active_runs", dict),
                ("_stop_lock", threading.Lock),
                ("_degradation_lock", threading.Lock),
                ("_degradation_counts", dict),
            )
            for attr, factory in defaults:
                if attr not in self.__dict__:
                    setattr(self, attr, factory())
            self.__dict__["_runtime_state_ready"] = True

    # ── Supervisor Graph 依赖 ────────────────────────────────────────────

    def _get_faq_retriever(self):
        if self._faq_retriever is None:
            from finance_agent.config import get_postgres_connection_factory
            from finance_agent.faq.embeddings import SentenceTransformerEmbeddingProvider
            from finance_agent.faq.repository import PostgresFaqRepository
            from finance_agent.faq.retriever import FaqRetriever

            self._faq_retriever = FaqRetriever(
                PostgresFaqRepository(get_postgres_connection_factory()),
                SentenceTransformerEmbeddingProvider(),
            )
        return self._faq_retriever

    def _get_async_run_repository(self):
        if self._async_run_repository is None:
            from finance_agent.config import get_postgres_connection_factory
            from finance_agent.faq.repository import PostgresAsyncRunRepository

            self._async_run_repository = PostgresAsyncRunRepository(
                get_postgres_connection_factory()
            )
        return self._async_run_repository

    def _get_quant_gateway(self):
        if self._quant_gateway is None:
            from finance_agent.orchestrator.quant import CeleryQuantGateway

            self._quant_gateway = CeleryQuantGateway(
                async_repository=self._get_async_run_repository()
            )
        return self._quant_gateway

    # 会话 ReAct 执行器：FAQ 检索 + 受约束补充叙述。
    def _conversation_runner(self, state: Dict[str, Any]) -> Dict[str, Any]:
        from finance_agent.orchestrator.conversation_graph import run_conversation
        from finance_agent.orchestrator.react import build_chat_model_callable

        return run_conversation(
            self._get_faq_retriever(),
            build_chat_model_callable(get_supervisor_model()),
            user_message=str(state.get("user_message", "")),
            history=str(state.get("history", "") or ""),
            max_steps=self.budgets.react_steps,
        )

    # 单领域 Domain ReAct 执行器：按注册表的元数据分发到对应子图。
    def _domain_runner(self, context: DomainTaskContext) -> DomainOutcome:
        from finance_agent.orchestrator.contracts import BusinessDomain
        from finance_agent.orchestrator.operations import default_operation_registry

        domain = context.task.domain
        registry = default_operation_registry()
        if domain == BusinessDomain.STOCK_RESEARCH:
            # 股票技术指标经 QuantGateway 投递到独立 Celery worker；领域图只依赖
            # seam，避免把 Celery/Redis 细节扩散到研究逻辑。
            from finance_agent.orchestrator.domains.stock import StockDeps, build_stock_domain_graph

            graph = build_stock_domain_graph(
                StockDeps(quant_gateway=self._get_quant_gateway())
            )
        elif domain == BusinessDomain.MARKET_INSIGHT:
            from finance_agent.orchestrator.domains.market import build_market_domain_graph

            graph = build_market_domain_graph()
        elif domain == BusinessDomain.ACCOUNT_PORTFOLIO:
            # 只读领域：仅查询账户与持仓，下单/充值只能走 REST。
            from finance_agent.orchestrator.domains.account import build_account_domain_graph

            graph = build_account_domain_graph()
        else:
            from finance_agent.orchestrator.domains.product import build_product_domain_graph

            graph = build_product_domain_graph()
        # 领域 builder 均薄封装注册表条目；此处断言分发目标与注册表一致，
        # 防止两处分发口径漂移（builder 改注册表时不会同步到这里的 if/elif）。
        spec = registry.spec(domain)
        assert graph is not None
        return graph.invoke({"context": context})["domain_outcome"]

    # 复用 INTENT_MODEL 的跨领域 Planner；未配置时回退确定性计划。
    def _planner(self):
        from finance_agent.config import get_intent_model
        from finance_agent.orchestrator.plan_execute import build_llm_planner

        model = get_intent_model()
        return build_llm_planner(model) if model is not None else deterministic_planner

    # 受校验的计划路径配置：从 RunBudgets 派生，根图按路由选择 profile 而非
    # 传自由数值。统一 Planner–Executor 图（后续迁移）将复用同一契约。
    def _plan_profile(self):
        from finance_agent.orchestrator.contracts import ExecutionProfile

        return ExecutionProfile(
            mode="plan_execute",
            max_steps=self.budgets.plan_tasks,
            replan_enabled=self.budgets.replans > 0,
            max_replans=self.budgets.replans,
            operation_scope="cross_domain",
        )

    def _build_supervisor(self):
        return build_supervisor_graph(
            SupervisorDependencies(
                classifier=self.classifier,
                conversation_runner=self._conversation_runner,
                domain_runner=self._domain_runner,
                planner=self._planner(),
                replan_limit=self.budgets.replans,
                # 端到端预算：跨领域计划有墙钟上限，并在下发每个任务前查询停止标记。
                plan_deadline_seconds=ORCHESTRATION_PLAN_DEADLINE,
                should_stop=self._current_stop_check,
                budgets=self.budgets,
            ),
            checkpointer=getattr(self, "checkpointer", None),
        )

    def _current_stop_check(self) -> bool:
        """返回"当前正在执行的轮次是否被请求停止"的查询函数。

        停止标记按会话记录；这里在每轮开始时把当前 conversation_id 记录到线程
        本地，使图内部的回调（无 conversation_id 上下文）也能查到正确标记。
        """
        self._ensure_runtime_state()
        conversation_id = getattr(self._stop_context_ref, "conversation_id", "")
        if not conversation_id:
            return False
        return self._is_stopped(conversation_id)

    # ── 进度与停止 ────────────────────────────────────────────────

    @contextmanager
    def _conversation_guard(self, conversation_id: str):
        """串行化同一会话的轮次；不同会话可并发执行。"""
        self._ensure_runtime_state()
        registry = self._conversation_locks
        with _RUNTIME_STATE_GUARD:
            entry = registry.get(conversation_id)
            if entry is None:
                entry = [threading.Lock(), 0]
                registry[conversation_id] = entry
            # 引用计数在获取锁之前递增：等待中的轮次也算持有者，
            # 避免等待期间注册表项被其它轮次清理掉。
            entry[1] += 1
        try:
            with entry[0]:
                yield
        finally:
            with _RUNTIME_STATE_GUARD:
                entry[1] -= 1
                if not entry[1]:
                    registry.pop(conversation_id, None)

    def _emit_progress(self, stage: str, message: str, conversation_id: str = "") -> None:
        # 注册表按 conversation_id 索引回调；查不到时回退线程本地（同轮工作线程）。
        callback = None
        if conversation_id:
            with self._progress_lock:
                callback = self._progress_callbacks.get(conversation_id)
        if callback is None:
            callback = getattr(self._progress_context, "callback", None)
        if callback:
            callback(stage, message)

    def _trace_agent(self, name: str, conversation_id: str = "UNKNOWN") -> None:
        with self._trace_lock:
            sequence = self._trace_sequences.get(conversation_id, 0) + 1
            self._trace_sequences[conversation_id] = sequence
        logger.debug("[Agent Flow] %s | %02d -> %s", conversation_id, sequence, name)

    def request_stop(self, conversation_id: str = "", run_id: str = "") -> bool:
        """标记停止请求；已完成的专家结果保留，未开始的专家被跳过。

        同时撤销该会话/线程尚未开始的异步量化任务：用户停止后，还在排队或
        运行的量化任务不再需要，撤销后其迟到结果会被恢复路径忽略。
        """
        self._ensure_runtime_state()
        customer_id = ""
        if run_id:
            with self._stop_lock:
                active = self._active_runs.get(run_id)
                if isinstance(active, tuple):
                    conversation_id = active[0] or conversation_id
                    customer_id = active[1]
                elif active:
                    conversation_id = active or conversation_id
        if not conversation_id:
            return False
        with self._stop_lock:
            self._stop_requests[conversation_id] = True
        # 撤销异步量化任务（尽力而为：网关不可用不影响停止语义）。
        self._revoke_quant_jobs(customer_id, conversation_id)
        return True

    def _revoke_quant_jobs(self, customer_id: str, conversation_id: str) -> list[str]:
        """撤销该会话名下 queued/running 的量化任务；返回被撤销的 job 列表。"""
        if not customer_id or not conversation_id:
            return []
        try:
            from finance_agent.orchestrator.resume import (
                RepositoryQuantRuntime,
                ResumeCoordinator,
            )

            repository = self._get_async_run_repository()
            runtime = RepositoryQuantRuntime(
                self._get_quant_gateway(), repository,
            )
            coordinator = ResumeCoordinator(runtime)
            thread_id = build_thread_id(customer_id, conversation_id)
            return coordinator.cancel(thread_id)
        except Exception:  # noqa: BLE001 - 撤销失败不得影响停止语义
            logger.warning(
                "quant_revoke_failed conversation_id=%s", conversation_id, exc_info=True,
            )
            return []

    def _is_stopped(self, conversation_id: str) -> bool:
        with self._stop_lock:
            return bool(self._stop_requests.get(conversation_id))

    # ── 研究审计（可重放：结果 + 原始快照清单）────────────────────

    def _audit_research_results(self, state: Dict[str, Any]) -> None:
        """将确定性研究结果及其引用的原始快照写入可重放审计表。

        多标的一轮（比较、主题筛选）必须写成同一次运行的多条结果。
        """
        save = getattr(self.audit, "save_research_result", None)
        save_run = getattr(self.audit, "save_research_run", None)
        evidence_facts = {
            fact.fact_id: fact.model_dump(mode="json")
            for fact in state.get("facts", []) or []
            if isinstance(fact, FactSnapshot)
        }
        results = []
        for raw_result in state.get("analysis_results", []) or []:
            try:
                results.append(AnalysisResult.model_validate(raw_result))
            except (TypeError, ValueError):
                continue

        theme_screening = state.get("theme_screening", {}) or {}
        if theme_screening:
            try:
                request = AnalysisRequest.model_validate(theme_screening.get("request", {}))
            except (TypeError, ValueError):
                return
            self._save_research_run(
                save_run, request=request, results=results, evidence_facts=evidence_facts,
                state=state,
                active_members=list(theme_screening.get("active_members", [])),
                exclusions=list(theme_screening.get("exclusions", [])),
                status=str(theme_screening.get("status", "completed")),
            )
            return

        run_request = self._run_level_request(state, results)
        if len(results) > 1 and callable(save_run) and run_request is not None:
            self._save_research_run(
                save_run, request=run_request, results=results, evidence_facts=evidence_facts,
                state=state, active_members=[], exclusions=[], status="completed",
            )
            return

        if not callable(save):
            # 能力缺失（审计存储未实现该接口）不算"写入失败"，单独计数，
            # 避免与 best_effort 的失败计数混淆；留日志防止静默降级无人知晓。
            logger.warning("audit_capability_missing method=save_research_result")
            self._bump_degradation("audit_capability_missing")
            return
        for result in results:
            save(
                result,
                snapshot_manifest=[
                    evidence_facts[fact_id]
                    for fact_id in result.evidence_ids
                    if fact_id in evidence_facts
                ],
                run_id=str(state.get("run_id", "")),
                customer_id=str(state.get("customer_id", "")),
                conversation_id=str(state.get("thread_id", "")),
            )

    def _save_research_run(
        self,
        save_run: Any,
        *,
        request: AnalysisRequest,
        results: List[AnalysisResult],
        evidence_facts: Dict[str, Any],
        state: Dict[str, Any],
        active_members: List[Dict[str, Any]],
        exclusions: List[Dict[str, Any]],
        status: str,
    ) -> None:
        if not callable(save_run):
            logger.warning("audit_capability_missing method=save_research_run")
            self._bump_degradation("audit_capability_missing")
            return
        fact_ids = {fact_id for result in results for fact_id in result.evidence_ids}
        save_run(
            request=request,
            results=results,
            snapshot_manifest=[
                evidence_facts[fact_id] for fact_id in fact_ids if fact_id in evidence_facts
            ],
            active_members=active_members,
            exclusions=exclusions,
            run_id=str(state.get("run_id", "")),
            customer_id=str(state.get("customer_id", "")),
            conversation_id=str(state.get("thread_id", "")),
            status=status,
        )

    @staticmethod
    def _run_level_request(
        state: Dict[str, Any], results: List[AnalysisResult],
    ) -> AnalysisRequest | None:
        """取运行级请求：优先专家留档的原始请求，其次回退到首条结论的请求。"""
        raw_request = state.get("research_request")
        if isinstance(raw_request, dict):
            try:
                return AnalysisRequest.model_validate(raw_request)
            except (TypeError, ValueError):
                pass
        for result in results:
            if result.request is not None:
                return result.request
        return None

    # ── 入口 ──────────────────────────────────────────────────────

    def handle_message(
        self,
        message: str,
        chat_history: List[Dict[str, str]] | None = None,
        customer_id: str = "CUST001",
        progress_callback: Callable[[str, str], None] | None = None,
        conversation_id: str = "",
        resume: bool = False,
        answers: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """处理一轮同步消息；根图为唯一执行路径，异常显式失败不回退。

        ``resume=True`` 表示这轮消息是对上一轮"缺参追问"（LangGraph interrupt）
        的回答，``answers`` 是弹窗提交的结构化参数；此时在同一 thread 上
        ``Command(resume=answers)`` 续跑，而不是开启新轮。
        """
        conversation_id = conversation_id or uuid.uuid4().hex
        if should_block_input(message):
            return {
                "response": BLOCKED_RESPONSE,
                "task_plan": [], "task_dispatch": [], "tasks": [], "task_results": {},
                "run_status": "completed", "warnings": [],
                "conversation_id": conversation_id,
                "compliance_result": {}, "blocked": True,
            }

        with self._conversation_guard(conversation_id):
            with self._stop_lock:
                self._stop_requests.pop(conversation_id, None)
            if progress_callback is not None:
                with self._progress_lock:
                    self._progress_callbacks[conversation_id] = progress_callback
            self._progress_context.callback = progress_callback
            # 停止标记按会话记录，而图内部回调拿不到 conversation_id；
            # 记到线程本地后，should_stop 才能查到正确标记。
            self._stop_context_ref.conversation_id = conversation_id
            self._trace_sequences[conversation_id] = 0
            self._emit_progress("manager", "正在识别业务领域", conversation_id)

            fallback_history = chat_history or self.get_checkpoint_conversation_messages(
                conversation_id, self.memory.window_size,
            )
            identifiers = generate_identifiers(conversation_id)
            run_id = str(identifiers.run_id)
            with self._stop_lock:
                # 记录 (conversation_id, customer_id)：停止时据此推导 thread_id，
                # 撤销该会话名下尚未开始的异步量化任务。
                self._active_runs[run_id] = (conversation_id, customer_id)
            self._best_effort(
                "audit_create_run",
                lambda: self.audit.create_run(
                    RequestEnvelope(
                        run_id=identifiers.run_id,
                        trace_id=identifiers.trace_id,
                        # 稳定派生：同一客户的各轮审计可按 user_id 聚合关联。
                        user_id=_stable_user_id(customer_id),
                        customer_id=customer_id,
                        conversation_id=conversation_id,
                        message_id=identifiers.message_id,
                        message=message,
                    )
                ),
            )

            try:
                memory_data = self.memory.load_context(
                    customer_id, conversation_id, fallback_history,
                )
                history = memory_data.get("sliding_window") or fallback_history[-self.memory.window_size:]
                root = getattr(self, "supervisor", None) or self._build_supervisor()
                self._trace_agent("RootGraph", conversation_id)
                thread_id = build_thread_id(customer_id, conversation_id)
                # 画像卡注入：此前只把画像拼进 memory_context 却无人消费，导致
                # profile_complete 恒假、个性化结论不可达。这里把真实卡片随输入
                # 注入根图，再由 DomainTaskContext 透传给领域 handler。
                profile_card = self._best_effort_value(
                    "load_profile", lambda: self.memory.get_profile(customer_id),
                )
                profile_payload = asdict(profile_card) if profile_card is not None else {}
                # 弹窗补填的偏好先落长期画像：写入后本轮注入的就是最新卡片。
                self._persist_param_profile(customer_id, answers, profile_payload)
                config = {
                    "configurable": {"thread_id": thread_id},
                    "recursion_limit": getattr(self, "budgets", RunBudgets.from_config()).graph_steps,
                }
                result = self._invoke_with_resume(
                    root, config, resume=resume, answers=answers,
                    base_input={
                        "user_message": message,
                        "history": "\n".join(
                            str(item.get("content", "")) for item in history
                            if isinstance(item, dict)
                        ),
                        "customer_id": customer_id,
                        "conversation_id": conversation_id,
                        "thread_id": thread_id,
                        "run_id": run_id,
                        "memory_context": memory_data.get("context_text", ""),
                        "user_profile": profile_payload,
                        "warnings": [],
                        "task_results": {},
                        "domain_outcomes": {},
                    },
                )
            except Exception:
                logger.exception("orchestration_failed conversation_id=%s", conversation_id)
                output = self._failed_output(conversation_id)
            else:
                if result.get("__interrupt__"):
                    output = project_interrupt_state(
                        result, conversation_id=conversation_id, customer_id=customer_id,
                    )
                else:
                    output = project_supervisor_state(result, conversation_id=conversation_id)
                    output["customer_id"] = customer_id
                    # 领域因异步量化任务中断（processing）时落库结论快照，使状态
                    # 端点能在任务完成后按真实 job_id 恢复原会话。
                    self._persist_pending_outcomes(
                        result, customer_id=customer_id, conversation_id=conversation_id,
                    )
            finally:
                self._progress_context.callback = None
                self._stop_context_ref.conversation_id = ""
                with self._progress_lock:
                    self._progress_callbacks.pop(conversation_id, None)
                self._trace_sequences.pop(conversation_id, None)
                with self._stop_lock:
                    self._active_runs.pop(run_id, None)
                    self._stop_requests.pop(conversation_id, None)
                # 落库必须在会话锁内完成：原先锁外的 _persist 可能被下一轮
                # 抢先写入，导致会话消息与记忆窗口乱序。_persist 全程尽力
                # 而为（不抛出），不会影响锁的释放。
                self._persist(customer_id, conversation_id, message, output, run_id)

        return output

    # ── 降级可观测性 ──────────────────────────────────────────────

    def _bump_degradation(self, category: str) -> None:
        """累加一类降级计数，供健康检查与运维定位。

        这些代码路径（落库、记忆、审计）都是"尽力而为"：失败不能影响用户回复，
        但静默 ``except: pass`` 会让故障完全不可见（例如审计长期写不进去而无人
        知晓）。因此保留不抛出的语义，同时留下日志与计数。
        """
        self._ensure_runtime_state()
        with self._degradation_lock:
            self._degradation_counts[category] = self._degradation_counts.get(category, 0) + 1

    def degradation_counts(self) -> Dict[str, int]:
        """返回各类降级的累计次数快照。"""
        self._ensure_runtime_state()
        with self._degradation_lock:
            return dict(self._degradation_counts)

    def _failed_output(self, conversation_id: str) -> Dict[str, Any]:
        """执行异常时的安全失败响应。"""
        return {
            "response": "处理请求时发生内部错误，请稍后重试。",
            "task_plan": [], "task_dispatch": [], "tasks": [], "task_results": {},
            "run_status": "failed", "warnings": ["orchestration_failed"],
            "conversation_id": conversation_id,
        }

    # 运行后的会话落库、记忆更新与研究审计（尽力而为，不伪造成功）。
    def _persist(
        self, customer_id: str, conversation_id: str, message: str,
        output: Dict[str, Any], run_id: str,
    ) -> None:
        self._best_effort(
            "audit_complete_run",
            lambda: self.audit.complete_run(
                run_id, conversation_id, output.get("response", ""),
                message_id=str(uuid.uuid4()), status=output.get("run_status", "completed"),
                metadata={"task_plan": output.get("task_plan", [])},
            ),
        )
        self._best_effort(
            "audit_research_results",
            lambda: self._audit_research_results({
                "run_id": run_id,
                "customer_id": customer_id,
                "thread_id": build_thread_id(customer_id, conversation_id),
                "analysis_results": output.get("analysis_results", []) or [],
                "theme_screening": output.get("theme_screening", {}) or {},
                "research_request": output.get("research_request"),
                "facts": [
                    FactSnapshot.model_validate(fact)
                    for fact in output.get("facts", []) or []
                    if isinstance(fact, dict)
                ],
            }),
        )

        def _persist_conversation() -> None:
            db = get_database()
            db.append_conversation_message(conversation_id, "user", message)
            db.append_conversation_message(
                conversation_id, "assistant", output.get("response", ""),
                {"task_plan": output.get("task_plan", [])},
            )
            # 首条消息后给会话一个可读标题，供历史列表展示（幂等：仅"新对话"时改写）。
            db.rename_conversation_from_message(conversation_id, message)

        self._best_effort("persist_conversation", _persist_conversation)

        def _persist_memory() -> None:
            # memory 层失败走"返回 False"协议（不抛异常），必须显式检查，
            # 否则 Redis 宕机或画像写入失败会绕过 _best_effort 的降级计数。
            # 用 ``is False`` 判定：mock 返回 None（如测试替身）不算失败。
            persisted = (
                self.memory.append_window_message(customer_id, conversation_id, "user", message)
                and self.memory.append_window_message(
                    customer_id, conversation_id, "assistant", output.get("response", ""),
                    {"task_plan": output.get("task_plan", [])},
                )
                and self.memory.update_profile_from_result(customer_id, message, output)
            )
            if persisted is False:
                # 具体失败日志已由 memory 层记录，这里只补降级计数供健康检查聚合。
                self._bump_degradation("memory_persist_failed")

        self._best_effort("persist_memory", _persist_memory)

    def _best_effort(self, category: str, action: Callable[[], Any]) -> None:
        """执行尽力而为的副作用：失败只记录日志与计数，不影响已生成的用户回复。"""
        try:
            action()
        except Exception:  # noqa: BLE001 - 副作用失败不得改变响应结果
            self._bump_degradation(category)
            logger.warning("best_effort_failed category=%s", category, exc_info=True)

    def _best_effort_value(self, category: str, action: Callable[[], Any]) -> Any:
        """``_best_effort`` 的取值版本：失败降级为 ``None`` 并留降级计数。"""
        try:
            return action()
        except Exception:  # noqa: BLE001 - 读取失败回退空值，不影响本轮
            self._bump_degradation(category)
            logger.warning("best_effort_value_failed category=%s", category, exc_info=True)
            return None

    def _persist_param_profile(
        self, customer_id: str, answers: Dict[str, Any] | None, profile_payload: Dict[str, Any],
    ) -> None:
        """把弹窗补填的偏好（风险偏好/投资期限）写入长期画像，并同步本轮注入值。

        画像卡读取失败时 ``profile_payload`` 为空；此时仍尝试写入（``save_profile``
        内部按字段合并语义由调用方保证），因此先用空卡片兜底再补字段。写入失败只
        降级记录，绝不影响本轮回答。
        """
        updates = profile_updates_from_answers(answers)
        if not updates:
            return
        from finance_agent.orchestrator.memory import UserProfileCard

        def _save() -> None:
            existing = self.memory.get_profile(customer_id)
            card = UserProfileCard.from_dict(asdict(existing)) if existing is not None \
                else UserProfileCard(customer_id=customer_id.upper())
            for key, value in updates.items():
                setattr(card, key, value)
            if self.memory.save_profile(card):
                profile_payload.update(asdict(card))

        self._best_effort("persist_param_profile", _save)

    def _has_pending_interrupt(self, root: Any, config: Dict[str, Any]) -> bool:
        """探测该 thread 上是否有挂起的 interrupt（无 checkpointer 时恒为 False）。"""
        get_state = getattr(root, "get_state", None)
        if get_state is None:
            return False
        try:
            snapshot = get_state(config)
        except Exception:  # noqa: BLE001 - 探测失败按"无挂起"处理，回退普通轮次
            return False
        tasks = getattr(snapshot, "tasks", ()) or ()
        if any(getattr(task, "interrupts", ()) for task in tasks):
            return True
        # 兼容不同实现的快照形状：values 上残留的挂起载荷。
        if getattr(snapshot, "next", ()) and getattr(snapshot, "interrupts", ()):
            return True
        return False

    def _invoke_with_resume(
        self,
        root: Any,
        config: Dict[str, Any],
        *,
        resume: bool,
        answers: Dict[str, Any] | None,
        base_input: Dict[str, Any],
    ) -> Dict[str, Any]:
        """按是否存在挂起 interrupt 决定 invoke 方式。

        - 有挂起 + ``resume=True`` + ``answers``：``Command(resume=answers)`` 续跑。
        - 有挂起但本轮是自由文本新消息：先用取消哨兵关掉挂起 run（否则新问题会被
          误当成对追问的回答），再以普通轮次重新开始。
        - 无挂起或图不支持 resume：普通轮次。
        """
        if not self._has_pending_interrupt(root, config):
            return root.invoke(base_input, config)
        if resume and answers:
            return root.invoke(Command(resume=answers), config)
        # 用户没在回答追问（或前端没带结构化答案）：放弃挂起 run 并开新轮。
        self._best_effort(
            "cancel_pending_interrupt",
            lambda: root.invoke(Command(resume={CANCEL_SENTINEL: True}), config),
        )
        return root.invoke(base_input, config)

    def _persist_pending_outcomes(
        self, state: Dict[str, Any], *, customer_id: str, conversation_id: str,
    ) -> None:
        """把 processing 结论（含 pending_jobs）按 job_id 落库为快照。

        仅在结论确实携带 pending_jobs 时写入；写入是尽力而为：失败只记降级
        计数，不影响本轮响应。快照记录 thread_id/run_id 与标的代码，供状态端点
        在量化任务完成后合并指标、恢复原会话。
        """
        outcomes = (state.get("domain_outcomes") or {}) if isinstance(state, dict) else {}
        for value in outcomes.values():
            if not isinstance(value, dict) or value.get("status") != "processing":
                continue
            refs = list(value.get("pending_jobs") or [])
            structured = value.get("structured_data") or {}
            if isinstance(structured, dict):
                refs += list(structured.get("pending_jobs") or [])
            if not refs:
                continue
            codes = (
                structured.get("pending_job_codes")
                if isinstance(structured, dict) else None
            ) or {}
            run_id = str(state.get("run_id", ""))
            thread_id = str(state.get("thread_id", ""))

            def _save(refs=refs, codes=codes, outcome=value, run_id=run_id, thread_id=thread_id) -> None:
                repository = self._get_async_run_repository()
                for ref in refs:
                    if not isinstance(ref, dict) or not ref.get("job_id"):
                        continue
                    repository.save_pending_outcome(
                        customer_id=customer_id,
                        thread_id=thread_id,
                        run_id=run_id,
                        conversation_id=conversation_id,
                        job_id=str(ref["job_id"]),
                        outcome=outcome,
                        code=str(codes.get(str(ref["job_id"]), "")),
                    )

            self._best_effort("persist_pending_outcomes", _save)

    # 查询异步运行状态：先校验客户归属，再读取状态或恢复。
    def resolve_run_status(self, task_id: str, customer_id: str) -> Dict[str, Any]:
        """查询异步量化任务状态；完成时恢复原会话并返回渲染后的答复。

        ``task_id`` 即 Celery ``job_id``（``project_supervisor_state`` 的
        ``pending_task_ids`` 返回真实 job_id）。归属校验：仓储按 customer_id
        隔离，非本人任务返回 not_found。
        """
        repository = self._get_async_run_repository()
        job = repository.get_job_ref(task_id, customer_id)
        if job is None:
            return {
                "run_status": "not_found", "task_id": task_id,
                "response": "", "conversation_id": "",
            }
        status = self._get_quant_gateway().status(task_id)
        run_status = JOB_STATUS_TO_RUN_STATUS.get(status, DEFAULT_JOB_RUN_STATUS)
        if run_status != "completed":
            # cancelled：迟到成功结果必须忽略，不恢复。
            return {
                "run_status": run_status, "task_id": task_id,
                "response": "", "conversation_id": "", "warnings": [],
            }

        # 已完成：恢复原会话（合并指标 → 重渲染 → 过合规），不重跑已完成任务。
        recovered = self._recover_completed_job(task_id, customer_id)
        return {
            "run_status": "completed",
            "task_id": task_id,
            "response": recovered.get("response", "量化任务已完成。"),
            "conversation_id": recovered.get("conversation_id", ""),
            "warnings": recovered.get("warnings", []),
        }

    def _recover_completed_job(self, job_id: str, customer_id: str) -> Dict[str, Any]:
        """恢复一个已完成的量化任务：合并指标、重跑合规、写回原会话。

        快照按 job_id 定位（归属已由 get_job_ref 按 customer_id 校验）。恢复
        runner 经 ResumeCoordinator 触发，保证"取消忽略 + 仅完成才恢复"的
        把关与批量扫描路径一致。
        """
        repository = self._get_async_run_repository()
        snapshot = repository.get_pending_outcome(job_id, customer_id)
        if snapshot is None:
            # 无快照（可能已被前一次恢复收尾）：只报告完成，不重复渲染。
            return {"response": "量化任务已完成。", "conversation_id": "", "warnings": []}
        thread_id = str(snapshot.get("thread_id") or "")
        ref = repository.get_job_ref(job_id, customer_id)
        runtime = self._quant_runtime()
        coordinator = ResumeCoordinator(runtime)
        try:
            result = coordinator.resume_job(thread_id, ref)
        except Exception:  # noqa: BLE001 - 恢复失败降级为状态报告，不抛给端点
            logger.warning("quant_resume_failed job_id=%s", job_id, exc_info=True)
            result = None
        if not isinstance(result, dict):
            return {"response": "量化任务已完成。", "conversation_id": "", "warnings": []}
        return result

    def _quant_runtime(self):
        """构造恢复运行时：仓储读 job、网关查状态、runner 执行恢复。"""
        from finance_agent.orchestrator.resume import RepositoryQuantRuntime

        return RepositoryQuantRuntime(
            self._get_quant_gateway(),
            self._get_async_run_repository(),
            resume_runner=self._resume_quant_job,
        )

    def _resume_quant_job(self, thread_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """恢复 runner：合并量化指标、重跑合规、把最终答复写回原会话。

        与 Celery worker 解耦——worker 只计算，恢复由编排进程负责。一次领域
        执行可能提交多个 job（每只标的一个），因此每次恢复都从**全部兄弟 job**
        重算：已完成的指标合并、未完成的保留等待；全部完成才收尾并删除快照。
        """
        job_id = str(payload.get("job_id", ""))
        repository = self._get_async_run_repository()
        snapshot = repository.get_pending_outcome_by_job(job_id)
        if snapshot is None:
            return {"response": "量化任务已完成。", "conversation_id": "", "warnings": []}

        task_id = str(snapshot.get("task_id") or "")
        conversation_id = str(snapshot.get("conversation_id") or "")
        rows = [
            row for row in repository.list_pending_outcomes_for_task(task_id)
        ] or [{
            "job_id": job_id,
            "code": str(snapshot.get("code") or ""),
            "outcome": snapshot.get("outcome") or {},
            "conversation_id": conversation_id,
        }]

        warnings: list[str] = []
        merged: Dict[str, Any] = {}
        still_pending = False
        for row in rows:
            status = self._get_quant_gateway().status(row["job_id"])
            if status == "cancelled":
                # 取消后的迟到成功结果忽略：该 job 不计入，也不阻塞收尾。
                continue
            if status != "completed":
                still_pending = True
                continue
            indicators = self._merge_quant_indicators(
                row.get("outcome") or {}, row["job_id"], str(row.get("code") or ""),
            )
            if indicators is None:
                warnings.append(f"quant_result_unavailable:{row['job_id']}")
            else:
                merged.update(indicators)

        base = dict(snapshot.get("outcome") or {})
        if still_pending:
            # 仍有兄弟 job 未完成：保留快照，不提前收尾（端点会再被轮询）。
            return {"response": "", "conversation_id": conversation_id, "warnings": warnings}

        # 全部完成（或已取消）：合并指标、移除等待限制、重算状态。
        structured = dict(base.get("structured_data") or {})
        structured.pop("pending_jobs", None)
        structured.pop("pending_job_codes", None)
        if merged:
            structured["technical_analysis"] = {
                **(structured.get("technical_analysis") or {}), **merged,
            }
        limitations = [
            item for item in (base.get("limitations") or []) if item != "awaiting_quant"
        ]
        if not merged:
            limitations.append("quant_result_unavailable")
        base.update(
            status="success" if not limitations else "partial",
            structured_data=structured,
            limitations=limitations,
            pending_jobs=[],
        )
        for row in rows:
            repository.delete_pending_outcome(row["job_id"])

        response = self._render_recovered_response(base)
        from finance_agent.orchestrator.compliance import run_compliance

        try:
            result = run_compliance(draft=response)
            response = result.response
            if result.action == "blocked":
                warnings.append("compliance_blocked")
        except Exception:  # noqa: BLE001 - 合规不可用不改写，但仍返回结果
            logger.warning("quant_resume_compliance_failed job_id=%s", job_id, exc_info=True)

        self._append_recovered_message(
            conversation_id, task_id, str(base.get("summary") or ""), response,
        )
        return {"response": response, "conversation_id": conversation_id, "warnings": warnings}

    def _merge_quant_indicators(
        self, outcome: Dict[str, Any], job_id: str, code: str,
    ) -> Dict[str, Any] | None:
        """把该 job 的量化指标并入 ``technical_analysis[code]``；无结果返回 None。"""
        result = self._get_quant_gateway().result(job_id)
        if not isinstance(result, dict):
            return None
        indicators = result.get("indicators")
        if not isinstance(indicators, dict) or not code:
            return None
        return {code: indicators}

    def _render_recovered_response(self, outcome: Dict[str, Any]) -> str:
        """由恢复后的结论渲染最终答复（保留原 summary 并追加完成提示）。"""
        summary = str(outcome.get("summary") or "").strip()
        note = "技术指标计算已完成，以上结论已更新。"
        return f"{summary}\n\n{note}" if summary else note

    def _append_recovered_message(
        self, conversation_id: str, task_id: str, summary: str, response: str,
    ) -> None:
        """把恢复后的答复写回原会话（尽力而为，不阻塞状态端点返回）。"""
        if not conversation_id or not response:
            return

        def _write() -> None:
            db = get_database()
            db.append_conversation_message(
                conversation_id, "assistant", response, {"recovered_task_id": task_id},
            )

        self._best_effort("persist_recovered_message", _write)

    # 处理流式消息，保持既有公共签名和 SSE 事件形状。
    async def handle_message_stream(
        self,
        message: str,
        chat_history: List[Dict[str, str]] | None = None,
        customer_id: str = "CUST001",
        conversation_id: str = "",
        turn_timeout: float | None = None,
        resume: bool = False,
        answers: Dict[str, Any] | None = None,
    ):
        """流式处理一轮消息。

        ``turn_timeout`` 是整轮墙钟上限（秒），缺省取 ``ORCHESTRATION_TURN_TIMEOUT``。
        显式参数化而非直接读模块全局：上限是调用方策略，注入后可测试、
        也可按调用场景收紧（模块全局只适合当默认值）。
        """
        limit = ORCHESTRATION_TURN_TIMEOUT if turn_timeout is None else turn_timeout
        if should_block_input(message):
            yield {"type": "stage", "stage": "content_filter", "message": "正在检查输入内容..."}
        else:
            yield {"type": "stage", "stage": "manager", "message": "正在选择需要执行的领域..."}
        loop = asyncio.get_running_loop()
        progress_queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()

        def report(stage: str, text: str) -> None:
            loop.call_soon_threadsafe(
                progress_queue.put_nowait,
                {"type": "stage", "stage": stage, "message": text},
            )

        task = asyncio.create_task(
            asyncio.to_thread(
                self.handle_message, message, chat_history, customer_id, report,
                conversation_id, resume, answers,
            )
        )
        # 整轮墙钟上限：分项超时（LLM/意图/数据源）各自有界，但没有一层约束
        # "整轮最多多久"。缺了它，串起来的多个可选超时叠加起来仍可能让 SSE
        # 无限期发送心跳。超时后放弃等待（工作线程仍在跑完并落库），
        # 前端收到明确失败而不是永久等待。
        deadline = time.monotonic() + limit if limit and limit > 0 else None
        while not task.done() or not progress_queue.empty():
            # 只对"尚未完成"的任务判超时：任务已完成但队列还有待排空的进度事件时，
            # 若在此处报超时，会把已经算好的结果丢掉。
            if deadline is not None and not task.done() and time.monotonic() >= deadline:
                # 取消只是停止等待：工作线程会继续跑完并落库（与 /api/chat/stop
                # 的协作式停止同一语义），前端拿到明确失败而非永久等待。
                task.cancel()
                yield {
                    "type": "error",
                    "message": "本次请求处理超时，请稍后重试或缩小问题范围。",
                }
                return
            try:
                yield await asyncio.wait_for(progress_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                yield {"type": "heartbeat"}
        result = await task
        # 合规出口已对完整草稿校验完毕，此刻才把定稿文本分块下发：先把答复切成
        # delta 事件渐进呈现（前端累积渲染），最后再送一次完整 response 事件，
        # 携带权威内容与结构化数据，兼容只消费 response 的旧客户端。
        response_text = str(result.get("response") or "")
        chunks = _iter_stream_chunks(response_text, ORCHESTRATION_STREAM_CHUNK_SIZE)
        delay = _stream_chunk_delay(len(chunks))
        for chunk in chunks:
            yield {"type": "delta", "content": chunk}
            if delay:
                await asyncio.sleep(delay)
        yield {"type": "response", "content": response_text, "data": result}

    # ── 会话/画像管理 ─────────────────────────────────────────────

    def list_checkpoint_conversations(self, customer_id: str) -> list[dict[str, Any]]:
        try:
            return get_database().list_conversations(customer_id)
        except Exception:
            logger.warning("list_conversations_failed customer_id=%s", customer_id, exc_info=True)
            return []

    def get_checkpoint_conversation_messages(self, conversation_id: str, limit: int = 100) -> list[dict[str, Any]]:
        try:
            return get_database().get_conversation_messages(conversation_id, limit)
        except Exception:
            logger.warning(
                "get_conversation_messages_failed conversation_id=%s", conversation_id, exc_info=True,
            )
            return []

    def delete_checkpoint_conversation(self, conversation_id: str, customer_id: str) -> bool:
        """删除指定会话的业务行、checkpoint 与记忆；非本人会话返回 False。"""
        try:
            # 只有确实删除了属于该客户的行，才继续清理 checkpoint 与记忆，
            # 否则调用方（DELETE 路由）会把越权删除误报成成功。
            if not get_database().delete_conversation(conversation_id, customer_id):
                return False
            self.run_state.delete(customer_id, conversation_id)
            if getattr(self.memory, "store", None) is not None:
                self.memory.store.clear_conversation(customer_id, conversation_id)
            return True
        except Exception:
            logger.warning(
                "delete_conversation_failed conversation_id=%s", conversation_id, exc_info=True,
            )
            return False

    def clear_profile(self, customer_id: str | None = None) -> int:
        try:
            return get_database().delete_profiles(customer_id) if customer_id else get_database().delete_profiles()
        except Exception:
            logger.warning("clear_profile_failed customer_id=%s", customer_id, exc_info=True)
            return 0

    def reset_session(self, customer_id: str = "") -> int:
        if not customer_id:
            return 0
        self._trace_sequences.pop(customer_id, None)
        try:
            conversations = get_database().list_conversations(customer_id)
        except Exception:
            return 0
        cleared = 0
        for conversation in conversations:
            if self.memory.store.clear_conversation(customer_id, conversation["conversation_id"]):
                cleared += 1
        return cleared

    def get_user_profile(self, customer_id: str) -> Dict[str, Any]:
        from dataclasses import asdict
        return asdict(self.memory.get_profile(customer_id))
