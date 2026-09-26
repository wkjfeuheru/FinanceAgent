"""金融投顾编排系统（LangGraph 唯一路径）。

对外保留既有同步/流式签名与响应字段；内部由 Supervisor Graph 统一承担分类、
任务改写、单领域专家 / 复合 Plan-and-Execute 调度、缺参处理与多域汇合，
所有输出经统一合规出口投影。四个业务领域由 ReAct 专家（``create_agent``
工具循环）承担，自主选择工具并解析参数。
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, List

from langgraph.types import Command

from finance_agent.infrastructure.settings import (
    ORCHESTRATION_STREAM_CHUNK_DELAY_MS,
    ORCHESTRATION_STREAM_CHUNK_SIZE,
    ORCHESTRATION_STREAM_MAX_SECONDS,
    ORCHESTRATION_TURN_TIMEOUT,
)
from finance_agent.infrastructure.llm.factory import get_supervisor_model
from finance_agent.bootstrap import AdvisorDependencies
from finance_agent.orchestration.contracts import (
    RUN_CANCELLED_WARNING,
    TURN_DEADLINE_WARNING,
    DomainOutcome,
    DomainTaskContext,
)
from finance_agent.orchestration.experts.base import STOP_CHECK_KEY
from finance_agent.orchestration.persistence_database import get_database
from finance_agent.orchestration.needs_input import (
    CANCEL_SENTINEL,
)
from finance_agent.application.async_recovery import QuantRecovery
from finance_agent.application.run_persistence import PersistenceCoordinator
from finance_agent.application.turn_coordinator import (
    TurnCoordinator,
    stable_user_id as _stable_user_id,
)
from finance_agent.orchestration.graphs.supervisor import (
    SupervisorDependencies,
    build_supervisor_graph,
)
from finance_agent.domains.research.contracts import AnalysisRequest, AnalysisResult
from finance_agent.safety.input_policy import is_trade_request, should_block_input

logger = logging.getLogger(__name__)


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
        # 重量级依赖经启动容器一次性解析：运行预算、检查点、业务库、运行状态、
        # 记忆、分类器与审计。运行预算的单一配置源：config.ORCHESTRATION_* →
        # 受校验 RunBudgets；会话 ReAct 步数、单轮领域扇出上限、缺参追问次数、
        # 合规改写次数与根图递归上限都从这里取值，不允许各模块再自带一份默认值。
        deps = AdvisorDependencies.build()
        self._deps = deps
        self.budgets = deps.budgets
        self.checkpointer = deps.checkpointer
        self.run_state = deps.run_state
        self.memory = deps.memory
        self.classifier = deps.classifier
        self.audit = deps.audit
        self._faq_retriever = None
        self._async_run_repository = None
        self._quant_gateway = None
        self.supervisor = self._build_supervisor()

    def _recovery(self) -> QuantRecovery:
        """异步量化恢复协作器；无状态，按需构造。"""
        return QuantRecovery(self)

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
                # 领域专家图按领域编译一次并复用（工具经 RunnableConfig 取
                # per-run sink，编译产物本身无状态）。
                ("_expert_graphs", dict),
                # 合规能力（语义校验器 / 受信判定 embedding）按需构建一次并缓存。
                ("_semantic_cache", dict),
                ("_embedding_cache", dict),
            )
            for attr, factory in defaults:
                if attr not in self.__dict__:
                    setattr(self, attr, factory())
            self.__dict__["_runtime_state_ready"] = True

    # ── Supervisor Graph 依赖 ────────────────────────────────────────────

    def _get_faq_retriever(self):
        """惰性构建 FAQ 检索器；构建逻辑在启动容器，实例字段负责缓存。"""
        if self._faq_retriever is None:
            self._faq_retriever = AdvisorDependencies.build_faq_retriever(
                self._get_faq_embedding_provider()
            )
        return self._faq_retriever

    def _get_faq_embedding_provider(self):
        """FAQ 向量化提供者（检索与合规受信判定共用同一实例，避免加载两份模型）。"""
        self._ensure_runtime_state()
        cached = self._embedding_cache.get("provider")
        if cached is None:
            cached = AdvisorDependencies.build_faq_embedding_provider()
            self._embedding_cache["provider"] = cached
        return cached

    def _get_semantic_check(self):
        """合规语义校验器（只输出违规码，不改写文本）。

        复用 INTENT_MODEL（便宜档）：模型不可用时返回 None（只做确定性检查），
        调用失败时校验器内部抛错 → 合规节点的错误处理器 fail-closed 拦截。
        """
        self._ensure_runtime_state()
        if "check" in self._semantic_cache:
            return self._semantic_cache["check"]
        from finance_agent.infrastructure.llm.factory import get_intent_model
        from finance_agent.orchestration.graphs.compliance import build_model_semantic_check

        model = get_intent_model()
        check = build_model_semantic_check(model) if model is not None else None
        self._semantic_cache["check"] = check
        return check

    def _get_async_run_repository(self):
        """惰性构建异步运行仓储（构建逻辑在启动容器）。"""
        if self._async_run_repository is None:
            self._async_run_repository = AdvisorDependencies.build_async_run_repository()
        return self._async_run_repository

    def _get_quant_gateway(self):
        """惰性构建量化网关；其仓储依赖同一实例的异步运行仓储。"""
        if self._quant_gateway is None:
            self._quant_gateway = AdvisorDependencies.build_quant_gateway(
                self._get_async_run_repository()
            )
        return self._quant_gateway

    # 会话 ReAct 执行器：FAQ 检索 + 受约束补充叙述（create_agent 原生工具循环）。
    def _conversation_runner(self, state: Dict[str, Any]) -> Dict[str, Any]:
        from finance_agent.orchestration.graphs.conversation import run_conversation

        return run_conversation(
            self._get_faq_retriever(),
            get_supervisor_model(),
            user_message=str(state.get("user_message", "")),
            history=str(state.get("history", "") or ""),
            max_steps=self.budgets.react_steps,
            stop_check=self._stop_reason_check(
                float((state.get("run") or {}).get("deadline_monotonic") or 0.0)
                if isinstance(state.get("run"), dict)
                else 0.0
            ),
        )

    def _stop_reason_check(self, deadline_monotonic: float):
        """构造"停止/截止查询"：返回原因码（空串表示继续）。

        唯一事实源在这里：用户停止标记（按会话记录）与整轮墙钟截止合并为一个
        可调用对象，经 ``RunnableConfig`` 下发给专家与汇合循环，使它们在
        **模型轮次边界**自行退出，而不是被外部强杀。
        """

        def check() -> str:
            if self._current_stop_check():
                return RUN_CANCELLED_WARNING
            if deadline_monotonic and time.monotonic() >= float(deadline_monotonic):
                return TURN_DEADLINE_WARNING
            return ""

        return check

    # 单领域与多领域统一由领域专家承担：按领域编译一次并复用。
    def _domain_runner(self, context: DomainTaskContext) -> DomainOutcome:
        from finance_agent.orchestration.experts import build_expert

        domain = context.task.domain
        graph = self._expert_graphs.get(domain)
        if graph is None:
            graph = build_expert(domain)
            self._expert_graphs[domain] = graph
        return graph.invoke(
            {"context": context},
            config={
                "configurable": {
                    STOP_CHECK_KEY: self._stop_reason_check(
                        context.turn_deadline_monotonic
                    )
                }
            },
        )["domain_outcome"]

    # 进度回调：图内节点经依赖注入调用它，落到当前 SSE 流（按会话路由）。
    def _report_progress(self, stage: str, message: str) -> None:
        self._emit_progress(stage, message)

    def _build_supervisor(self):
        return build_supervisor_graph(
            SupervisorDependencies(
                classifier=self.classifier,
                conversation_runner=self._conversation_runner,
                domain_runner=self._domain_runner,
                # 停止与整轮截止由宿主下发（专家在模型轮次边界检查），
                # 预算与进度同样经依赖注入，图内不反向引用宿主。
                should_stop=self._current_stop_check,
                progress=self._report_progress,
                budgets=self.budgets,
                # 合规能力：语义校验（只出违规码）与句级受信判定的向量化。
                semantic_check=self._get_semantic_check(),
                trust_embeddings=self._get_faq_embedding_provider(),
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

    def lookup_active_run(self, run_id: str) -> tuple[str, str] | None:
        """返回运行对应的会话与客户，供停止接口先完成归属校验。"""
        self._ensure_runtime_state()
        with self._stop_lock:
            active = self._active_runs.get(run_id)
            if isinstance(active, tuple) and len(active) == 2:
                return str(active[0] or ""), str(active[1] or "")
        return None

    def _revoke_quant_jobs(self, customer_id: str, conversation_id: str) -> list[str]:
        """撤销该会话名下尚未开始的量化任务（委托恢复协作器）。"""
        return self._recovery().revoke_quant_jobs(customer_id, conversation_id)

    def _is_stopped(self, conversation_id: str) -> bool:
        with self._stop_lock:
            return bool(self._stop_requests.get(conversation_id))

    # ── 研究审计（可重放：结果 + 原始快照清单）────────────────────

    def _persistence(self) -> PersistenceCoordinator:
        """构造轻量持久化协作器，并保留 advisor 模块的数据库替换接缝。"""
        return PersistenceCoordinator(self, get_database)

    def _audit_research_results(self, state: Dict[str, Any]) -> None:
        """保留历史调用点，将研究审计委托给持久化协作器。"""
        self._persistence().audit_research_results(state)

    def _save_research_run(
        self,
        save_run: Any,
        *,
        request: AnalysisRequest,
        results: List[AnalysisResult],
        evidence_facts: Dict[str, Any],
        state: Dict[str, Any],
        status: str,
    ) -> None:
        self._persistence().save_research_run(
            save_run, request=request, results=results, evidence_facts=evidence_facts,
            state=state, status=status,
        )

    @staticmethod
    def _run_level_request(
        state: Dict[str, Any], results: List[AnalysisResult],
    ) -> AnalysisRequest | None:
        """兼容旧调用点，委托运行级请求解析。"""
        return PersistenceCoordinator._run_level_request(state, results)

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
        return TurnCoordinator(self).handle_message(
            message,
            chat_history=chat_history,
            customer_id=customer_id,
            progress_callback=progress_callback,
            conversation_id=conversation_id,
            resume=resume,
            answers=answers,
        )

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
        self._persistence().persist(customer_id, conversation_id, message, output, run_id)

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
        self._persistence().persist_param_profile(customer_id, answers, profile_payload)

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
        """把 processing 结论按 job_id 落库为快照（委托恢复协作器）。"""
        self._recovery().persist_pending_outcomes(
            state, customer_id=customer_id, conversation_id=conversation_id,
        )

    # 查询异步运行状态：先校验客户归属，再读取状态或恢复。
    def resolve_run_status(self, task_id: str, customer_id: str) -> Dict[str, Any]:
        """查询异步量化任务状态；完成时恢复原会话（委托恢复协作器）。"""
        return self._recovery().resolve_run_status(task_id, customer_id)

    def _recover_completed_job(self, job_id: str, customer_id: str) -> Dict[str, Any]:
        """恢复一个已完成的量化任务（委托恢复协作器）。"""
        return self._recovery().recover_completed_job(job_id, customer_id)

    def _quant_runtime(self):
        """构造恢复运行时（委托恢复协作器）。"""
        return self._recovery().quant_runtime()

    def _resume_quant_job(self, thread_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """恢复 runner：合并量化指标、重跑合规、写回原会话（委托恢复协作器）。"""
        return self._recovery().resume_quant_job(thread_id, payload)

    def _merge_quant_indicators(
        self, outcome: Dict[str, Any], job_id: str, code: str,
    ) -> Dict[str, Any] | None:
        """把该 job 的量化指标并入 ``technical_analysis[code]``（委托恢复协作器）。"""
        return self._recovery().merge_quant_indicators(outcome, job_id, code)

    def _render_recovered_response(self, outcome: Dict[str, Any]) -> str:
        """由恢复后的结论渲染最终答复（委托恢复协作器）。"""
        return QuantRecovery.render_recovered_response(outcome)

    def _append_recovered_message(
        self, conversation_id: str, task_id: str, summary: str, response: str,
    ) -> None:
        """把恢复后的答复写回原会话（委托恢复协作器）。"""
        self._recovery().append_recovered_message(
            conversation_id, task_id, summary, response,
        )

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
        if should_block_input(message) or is_trade_request(message):
            # 敏感词与交易拒绝都在 handle_message 内提前返回；此处只对齐
            # 阶段事件，让前端知道这轮不会进入领域选择。
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
