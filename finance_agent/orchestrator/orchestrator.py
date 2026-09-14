"""金融投顾编排系统（LangGraph V2 唯一路径）。

对外保留既有同步/流式签名与响应字段；内部由 Root Graph 统一承担分类、路由、
单领域 Domain ReAct / 复合 Plan-and-Execute 调度，所有输出经统一合规出口投影。
"""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from typing import Any, Callable, Dict, List

from finance_agent.config import get_checkpoint_saver, get_supervisor_model
from finance_agent.contracts import FactSnapshot, RequestEnvelope, generate_identifiers
from finance_agent.data.postgres_repository import PostgresAuditStore
from finance_agent.orchestrator.contracts import DomainOutcome, DomainTaskContext
from finance_agent.orchestrator.database import get_database
from finance_agent.orchestrator.intent import IntentClassifier
from finance_agent.orchestrator.memory import AgentMemoryContext, RedisMemoryStore
from finance_agent.orchestrator.plan_execute import deterministic_planner
from finance_agent.orchestrator.root_graph import (
    RootGraphDependencies,
    build_root_graph,
    project_root_state,
)
from finance_agent.orchestrator.run_state import RunStateStore
from finance_agent.orchestrator.thread_key import build_thread_id
from finance_agent.research.contracts import AnalysisRequest, AnalysisResult
from finance_agent.middleware import BLOCKED_RESPONSE, find_sensitive_word

logger = logging.getLogger(__name__)


class AdvisorSystem:
    """金融投顾编排系统（Root Graph 为唯一执行路径）。"""

    def __init__(self):
        self.checkpointer = get_checkpoint_saver()
        self.run_state = RunStateStore(
            checkpointer=self.checkpointer,
            business_store=get_database(),
        )
        self.memory = AgentMemoryContext(
            store=RedisMemoryStore(), checkpointer=self.checkpointer,
        )
        self.classifier = IntentClassifier()
        self._progress_context = threading.local()
        self._progress_callbacks: Dict[str, Callable[[str, str], None]] = {}
        self._progress_lock = threading.Lock()
        self._trace_lock = threading.Lock()
        self._trace_sequences: Dict[str, int] = {}
        self._workflow_lock = threading.RLock()
        self._stop_requests: Dict[str, bool] = {}
        self._active_runs: Dict[str, str] = {}
        self._stop_lock = threading.Lock()
        self.audit = PostgresAuditStore.from_config()
        self._faq_retriever = None
        self._async_run_repository = None
        self._quant_gateway = None
        self.root = self._build_root()

    # ── Root Graph 依赖 ────────────────────────────────────────────

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
        )

    # 单领域 Domain ReAct 执行器：按领域分发到对应子图。
    def _domain_runner(self, context: DomainTaskContext) -> DomainOutcome:
        from finance_agent.orchestrator.contracts import BusinessDomain
        from finance_agent.orchestrator.domains.market import build_market_domain_graph
        from finance_agent.orchestrator.domains.product import build_product_domain_graph
        from finance_agent.orchestrator.domains.stock import StockDeps, build_stock_domain_graph

        if context.task.domain == BusinessDomain.STOCK_RESEARCH:
            graph = build_stock_domain_graph(StockDeps())
        elif context.task.domain == BusinessDomain.MARKET_INSIGHT:
            graph = build_market_domain_graph()
        else:
            graph = build_product_domain_graph()
        return graph.invoke({"context": context})["domain_outcome"]

    # 复用 INTENT_MODEL 的跨领域 Planner；未配置时回退确定性计划。
    def _planner(self):
        from finance_agent.config import get_intent_model
        from finance_agent.orchestrator.plan_execute import build_llm_planner

        model = get_intent_model()
        return build_llm_planner(model) if model is not None else deterministic_planner

    def _build_root(self):
        return build_root_graph(
            RootGraphDependencies(
                classifier=self.classifier,
                conversation_runner=self._conversation_runner,
                domain_runner=self._domain_runner,
                planner=self._planner(),
            )
        )

    # ── 进度与停止 ────────────────────────────────────────────────

    def _emit_progress(self, stage: str, message: str, thread_id: str = "") -> None:
        callback = None
        if thread_id:
            with self._progress_lock:
                callback = self._progress_callbacks.get(thread_id)
        if callback is None:
            callback = getattr(self._progress_context, "callback", None)
        if callback:
            callback(stage, message)

    def _trace_agent(self, name: str, thread_id: str = "UNKNOWN") -> None:
        with self._trace_lock:
            sequence = self._trace_sequences.get(thread_id, 0) + 1
            self._trace_sequences[thread_id] = sequence
        logger.debug("[Agent Flow] %s | %02d -> %s", thread_id, sequence, name)

    def request_stop(self, conversation_id: str = "", run_id: str = "") -> bool:
        """标记停止请求；已完成的专家结果保留，未开始的专家被跳过。"""
        if run_id:
            with self._stop_lock:
                conversation_id = self._active_runs.get(run_id, conversation_id)
        if not conversation_id:
            return False
        with self._stop_lock:
            self._stop_requests[conversation_id] = True
        return True

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
    ) -> Dict[str, Any]:
        """处理一轮同步消息；根图为唯一执行路径，异常显式失败不回退。"""
        conversation_id = conversation_id or uuid.uuid4().hex
        if find_sensitive_word(message) is not None:
            return {
                "response": BLOCKED_RESPONSE,
                "task_plan": [], "task_dispatch": [], "tasks": [], "task_results": {},
                "run_status": "completed", "warnings": [],
                "conversation_id": conversation_id,
                "compliance_result": {}, "blocked": True,
            }

        with self._workflow_lock:
            with self._stop_lock:
                self._stop_requests.pop(conversation_id, None)
            if progress_callback is not None:
                with self._progress_lock:
                    self._progress_callbacks[conversation_id] = progress_callback
            self._progress_context.callback = progress_callback
            self._trace_sequences[conversation_id] = 0
            self._emit_progress("manager", "正在识别业务领域", conversation_id)

            fallback_history = chat_history or self.get_checkpoint_conversation_messages(
                conversation_id, self.memory.window_size,
            )
            identifiers = generate_identifiers(conversation_id)
            run_id = str(identifiers.run_id)
            with self._stop_lock:
                self._active_runs[run_id] = conversation_id
            try:
                self.audit.create_run(
                    RequestEnvelope(
                        run_id=identifiers.run_id,
                        trace_id=identifiers.trace_id,
                        user_id=uuid.uuid4(),
                        customer_id=customer_id,
                        conversation_id=conversation_id,
                        message_id=identifiers.message_id,
                        message=message,
                    )
                )
            except Exception:
                pass

            try:
                memory_data = self.memory.load_context(
                    customer_id, conversation_id, fallback_history,
                )
                history = memory_data.get("sliding_window") or fallback_history[-self.memory.window_size:]
                root = getattr(self, "root", None) or self._build_root()
                self._trace_agent("RootGraph", conversation_id)
                result = root.invoke(
                    {
                        "user_message": message,
                        "history": "\n".join(
                            str(item.get("content", "")) for item in history
                            if isinstance(item, dict)
                        ),
                        "customer_id": customer_id,
                        "conversation_id": conversation_id,
                        "thread_id": build_thread_id(customer_id, conversation_id),
                        "run_id": run_id,
                        "memory_context": memory_data.get("context_text", ""),
                        "warnings": [],
                        "task_results": {},
                        "domain_outcomes": {},
                    }
                )
            except Exception:
                logger.exception("orchestration_failed conversation_id=%s", conversation_id)
                output = self._failed_output(conversation_id)
            else:
                output = project_root_state(result, conversation_id=conversation_id)
                output["customer_id"] = customer_id
            finally:
                self._progress_context.callback = None
                with self._progress_lock:
                    self._progress_callbacks.pop(conversation_id, None)
                self._trace_sequences.pop(conversation_id, None)
                with self._stop_lock:
                    self._active_runs.pop(run_id, None)
                    self._stop_requests.pop(conversation_id, None)

        self._persist(customer_id, conversation_id, message, output, run_id)
        return output

    def _failed_output(self, conversation_id: str) -> Dict[str, Any]:
        """执行异常时的安全失败响应。"""
        return {
            "response": "处理请求时发生内部错误，请稍后重试。",
            "task_plan": [], "task_dispatch": [], "tasks": [], "task_results": {},
            "run_status": "failed", "warnings": ["orchestration_failed"],
            "conversation_id": conversation_id,
        }

    # 运行后的会话落库、记忆更新与研究审计（失败静默，不伪造成功）。
    def _persist(
        self, customer_id: str, conversation_id: str, message: str,
        output: Dict[str, Any], run_id: str,
    ) -> None:
        try:
            self.audit.complete_run(
                run_id, conversation_id, output.get("response", ""),
                message_id=str(uuid.uuid4()), status=output.get("run_status", "completed"),
                metadata={"task_plan": output.get("task_plan", [])},
            )
        except Exception:
            pass
        try:
            self._audit_research_results({
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
            })
        except Exception:
            pass
        try:
            db = get_database()
            db.append_conversation_message(conversation_id, "user", message)
            db.append_conversation_message(
                conversation_id, "assistant", output.get("response", ""),
                {"task_plan": output.get("task_plan", [])},
            )
        except Exception:
            pass
        try:
            self.memory.append_window_message(conversation_id, "user", message)
            self.memory.append_window_message(
                conversation_id, "assistant", output.get("response", ""),
                {"task_plan": output.get("task_plan", [])},
            )
            self.memory.update_profile_from_result(customer_id, message, output)
        except Exception:
            pass

    # 查询异步运行状态：先校验客户归属，再读取状态。
    def resolve_run_status(self, task_id: str, customer_id: str) -> Dict[str, Any]:
        job = self._get_async_run_repository().get_job_ref(task_id, customer_id)
        if job is None:
            return {"run_status": "not_found", "task_id": task_id, "response": "", "conversation_id": ""}
        status = self._get_quant_gateway().status(task_id)
        run_status = {
            "queued": "processing", "running": "processing", "completed": "completed",
            "failed": "failed", "cancelled": "cancelled",
        }.get(status, "processing")
        return {
            "run_status": run_status,
            "task_id": task_id,
            "response": "量化任务已完成。" if run_status == "completed" else "",
            "conversation_id": "",
            "warnings": [],
        }

    # 处理流式消息，保持既有公共签名和 SSE 事件形状。
    async def handle_message_stream(
        self,
        message: str,
        chat_history: List[Dict[str, str]] | None = None,
        customer_id: str = "CUST001",
        conversation_id: str = "",
    ):
        if find_sensitive_word(message) is not None:
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
            asyncio.to_thread(self.handle_message, message, chat_history, customer_id, report, conversation_id)
        )
        while not task.done() or not progress_queue.empty():
            try:
                yield await asyncio.wait_for(progress_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                yield {"type": "heartbeat"}
        result = await task
        yield {"type": "response", "content": result["response"], "data": result}

    # ── 会话/画像管理 ─────────────────────────────────────────────

    def list_checkpoint_conversations(self, customer_id: str) -> list[dict[str, Any]]:
        try:
            return get_database().list_conversations(customer_id)
        except Exception:
            return []

    def get_checkpoint_conversation_messages(self, conversation_id: str, limit: int = 100) -> list[dict[str, Any]]:
        try:
            return get_database().get_conversation_messages(conversation_id, limit)
        except Exception:
            return []

    def delete_checkpoint_conversation(self, conversation_id: str, customer_id: str) -> bool:
        try:
            get_database().delete_conversation(conversation_id, customer_id)
            self.run_state.delete(customer_id, conversation_id)
            if getattr(self.memory, "store", None) is not None:
                self.memory.store.clear_conversation(conversation_id)
            return True
        except Exception:
            return False

    def clear_profile(self, customer_id: str | None = None) -> int:
        try:
            return get_database().delete_profiles(customer_id) if customer_id else get_database().delete_profiles()
        except Exception:
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
            if self.memory.store.clear_conversation(conversation["conversation_id"]):
                cleared += 1
        return cleared

    def get_user_profile(self, customer_id: str) -> Dict[str, Any]:
        from dataclasses import asdict
        return asdict(self.memory.get_profile(customer_id))
