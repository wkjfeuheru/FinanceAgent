"""金融投顾总管-专家编排系统。"""

from __future__ import annotations

import asyncio
import copy
import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from finance_agent.agents.casual_chat import CasualChatAgent
from finance_agent.agents.market_insight import MarketInsightAgent
from finance_agent.agents.product_analysis import ProductAnalysisAgent
from finance_agent.agents.stock_analysis import StockAnalysisAgent
from finance_agent.agents.supervisor import ManagerAgent
from finance_agent import config as app_config
from finance_agent.config import get_checkpoint_saver, get_supervisor_model
from finance_agent.contracts import (
    ExpertResult,
    ExpertStatus,
    FactSnapshot,
    RequestEnvelope,
    RunStatus,
    TaskStatus,
    generate_identifiers,
)
from finance_agent.data.postgres_repository import PostgresAuditStore
from finance_agent.orchestrator.contracts import DomainOutcome, DomainTaskContext
from finance_agent.orchestrator.root_graph import (
    RootGraphDependencies,
    build_root_graph,
    project_root_state,
)
from finance_agent.orchestrator.run_state import RunStateStore
from finance_agent.orchestrator.thread_key import build_thread_id
from finance_agent.orchestrator.tools.stockdata import fetch_stock_data
from finance_agent.research.contracts import AnalysisRequest, AnalysisResult
from finance_agent.orchestrator.database import get_database
from finance_agent.orchestrator.memory import AgentMemoryContext, RedisMemoryStore
from finance_agent.orchestrator.slots import SlotExtractor
from finance_agent.orchestrator.context_builder import build_task_context
from finance_agent.orchestrator.scheduler import TaskContext, run_task_dag
from finance_agent.orchestrator.state import AdvisorState, dedupe_concat, merge_dict
from finance_agent.middleware import BLOCKED_RESPONSE, find_sensitive_word

logger = logging.getLogger(__name__)

# 按专家放宽 DAG 预算：股票任务的取数是批次内并行外部 I/O，整批耗时随标的数增长，
# 沿用其它专家的 90s/180s 会在慢网络下截断整批（重构前该路径无超时）。
_DAG_BUDGETS: Dict[str, Dict[str, float]] = {
    "stock_analysis": {"timeout_seconds": 120, "deadline_seconds": 300},
}


class AdvisorSystem:
    """金融投顾总管-专家系统。"""

    # 初始化 checkpoint、记忆和四类业务专家。
    def __init__(self):
        self.checkpointer = get_checkpoint_saver()
        self.memory = AgentMemoryContext(
            store=RedisMemoryStore(), checkpointer=self.checkpointer,
        )
        self.manager = ManagerAgent(checkpointer=self.checkpointer)
        self.stock_agent = StockAnalysisAgent(checkpointer=self.checkpointer)
        self.market_insight_agent = MarketInsightAgent()
        self.product_agent = ProductAnalysisAgent(checkpointer=self.checkpointer)
        self.casual_chat_agent = CasualChatAgent()
        self.slot_extractor = SlotExtractor()
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
        self.graph = self._build_graph()
        # V2 编排默认关闭；开启时根图为唯一执行路径，异常不得静默回退旧路径。
        self._orchestration_v2 = bool(app_config.ORCHESTRATION_V2_ENABLED)
        self._v2_root = None
        if self._orchestration_v2:
            self._v2_root = self._build_v2_root()

    # 构造 V2 根图的运行依赖（分类器 + 会话执行器；领域/计划执行器在后续任务接入）。
    def _get_v2_classifier(self):
        manager = getattr(self, "manager", None)
        if manager is not None and hasattr(manager, "classify_intents"):
            return manager
        return ManagerAgent()

    def _get_async_run_repository(self):
        if getattr(self, "_async_run_repository", None) is None:
            from finance_agent.config import get_postgres_connection_factory
            from finance_agent.faq.repository import PostgresAsyncRunRepository

            self._async_run_repository = PostgresAsyncRunRepository(
                get_postgres_connection_factory()
            )
        return self._async_run_repository

    def _get_quant_gateway(self):
        if getattr(self, "_quant_gateway", None) is None:
            from finance_agent.orchestrator.quant import CeleryQuantGateway

            self._quant_gateway = CeleryQuantGateway(
                async_repository=self._get_async_run_repository()
            )
        return self._quant_gateway

    # 查询异步运行状态：先校验客户归属，再读取状态并尝试恢复。
    def resolve_run_status(self, task_id: str, customer_id: str) -> Dict[str, Any]:
        repository = self._get_async_run_repository()
        job = repository.get_job_ref(task_id, customer_id)
        if job is None:
            return {
                "run_status": "not_found",
                "task_id": task_id,
                "response": "",
                "conversation_id": "",
            }
        status = self._get_quant_gateway().status(task_id)
        run_status = {
            "queued": "processing",
            "running": "processing",
            "completed": "completed",
            "failed": "failed",
            "cancelled": "cancelled",
        }.get(status, "processing")
        return {
            "run_status": run_status,
            "task_id": task_id,
            "response": "" if run_status != "completed" else "量化任务已完成。",
            "conversation_id": "",
            "warnings": [],
        }

    def _get_faq_retriever(self):
        if getattr(self, "_faq_retriever", None) is None:
            from finance_agent.config import get_postgres_connection_factory
            from finance_agent.faq.embeddings import SentenceTransformerEmbeddingProvider
            from finance_agent.faq.repository import PostgresFaqRepository
            from finance_agent.faq.retriever import FaqRetriever

            self._faq_retriever = FaqRetriever(
                PostgresFaqRepository(get_postgres_connection_factory()),
                SentenceTransformerEmbeddingProvider(),
            )
        return self._faq_retriever

    # 会话 ReAct 执行器：FAQ 检索 + 受约束补充叙述。
    def _v2_conversation_runner(self, state: Dict[str, Any]) -> Dict[str, Any]:
        from finance_agent.orchestrator.conversation_graph import run_conversation
        from finance_agent.orchestrator.react import build_chat_model_callable

        retriever = self._get_faq_retriever()
        model = build_chat_model_callable(get_supervisor_model())
        return run_conversation(
            retriever,
            model,
            user_message=str(state.get("user_message", "")),
            history=str(state.get("history", "") or ""),
        )

    # 单领域 Domain ReAct 执行器：按领域分发到对应子图。
    def _v2_domain_runner(self, context: DomainTaskContext) -> DomainOutcome:
        from finance_agent.orchestrator.domains.market import build_market_domain_graph
        from finance_agent.orchestrator.domains.product import build_product_domain_graph
        from finance_agent.orchestrator.domains.stock import StockDeps, build_stock_domain_graph

        if context.task.domain == BusinessDomain.STOCK_RESEARCH:
            graph = build_stock_domain_graph(StockDeps())
        elif context.task.domain == BusinessDomain.MARKET_INSIGHT:
            graph = build_market_domain_graph()
        else:
            graph = build_product_domain_graph()
        result = graph.invoke({"context": context})
        return result["domain_outcome"]

    # 跨领域 Plan-and-Execute：Planner 生成计划，统一 Send 调度执行。
    def _v2_plan_runner(self, state: Dict[str, Any], domains: list) -> list[DomainOutcome]:
        from finance_agent.orchestrator.plan_execute import deterministic_planner, run_plan_execute

        plan = deterministic_planner(state, list(domains))
        result = run_plan_execute(
            domain_runner=self._v2_domain_runner,
            initial_plan=plan,
            thread_id=str(state.get("thread_id", "")),
            run_id=str(state.get("run_id", "")),
            customer_id=str(state.get("customer_id", "")),
            conversation_id=str(state.get("conversation_id", "")),
            user_message=str(state.get("user_message", "")),
        )
        return result["outcomes"]

    def _get_v2_planner(self):
        # 复用 INTENT_MODEL；未配置时返回 None，由确定性回退计划兜底。
        from finance_agent.config import get_intent_model
        from finance_agent.orchestrator.plan_execute import build_llm_planner

        model = get_intent_model()
        if model is None:
            return None
        return build_llm_planner(model)

    def _build_v2_root(self):
        from finance_agent.orchestrator.plan_execute import deterministic_planner

        return build_root_graph(
            RootGraphDependencies(
                classifier=self._get_v2_classifier(),
                conversation_runner=self._v2_conversation_runner,
                domain_runner=self._v2_domain_runner,
                plan_runner=self._v2_plan_runner,
                planner=self._get_v2_planner() or deterministic_planner,
            )
        )

    # 向当前请求注册并发送阶段进度。
    def _emit_progress(self, stage: str, message: str, thread_id: str = "") -> None:
        """发送阶段进度。

        DAG 的专家执行在工作线程里（``run_task_dag`` 的线程池），而进度回调只
        注册在主线程的 thread-local 上，因此**必须按 thread_id 查注册表**才能
        从工作线程送达；thread-local 只作为无 thread_id 时的兜底（兼容旧调用）。
        """
        callback = None
        if thread_id:
            with self._progress_lock:
                callback = self._progress_callbacks.get(thread_id)
        if callback is None:
            callback = getattr(self._progress_context, "callback", None)
        if callback:
            callback(stage, message)

    # 记录真实的总管和专家执行顺序。
    def _trace_agent(self, state: Dict[str, Any], name: str) -> None:
        thread_id = str(state.get("thread_id", "UNKNOWN"))
        with self._trace_lock:
            sequence = self._trace_sequences.get(thread_id, 0) + 1
            self._trace_sequences[thread_id] = sequence
        logger.debug("[Agent Flow] %s | %02d -> %s", thread_id, sequence, name)

    # 请求停止指定会话/运行。
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

    # 将单个专家结果写入 PostgreSQL 运行审计（可选，失败静默）。
    def _audit_expert_result(self, state: Dict[str, Any], expert: str, task: Any = None) -> None:
        if not self.audit.is_available():
            return
        run_id = str(state.get("run_id", "") or "")
        trace_id = str(state.get("trace_id", "") or "")
        if not run_id:
            return
        if expert == "stock_analysis":
            # 研究结果审计**不在此处触发**：这里拿到的是尚未合并本任务结果的共享
            # state，用它写 research_runs 会先删掉该运行既有行、写入过期内容。
            # 调用方在合并回本任务状态后再审计一次（每个任务恰好一次）。
            result_data = {
                "stock_data": state.get("stock_data", {}),
                "stock_analysis": state.get("stock_analysis", {}),
                "technical_analysis": state.get("technical_analysis", {}),
                "analysis_results": state.get("analysis_results", []),
                "theme_screening": state.get("theme_screening", {}),
            }
        elif expert == "market_insight":
            result_data = {"market_insight": state.get("market_insight", {})}
        elif expert == "product_analysis":
            result_data = {"product_analysis": state.get("product_analysis", {})}
        else:
            result_data = state.get("intent_results", {}).get("casual_chat", {})
        if task is not None:
            task_result = (state.get("task_results", {}) or {}).get(task.task_id)
            if isinstance(task_result, ExpertResult):
                self.audit.upsert_expert_result(run_id, trace_id, task_result)
                return
        self.audit.upsert_expert_result(
            run_id,
            trace_id,
            ExpertResult(
                expert_name=expert,
                status=ExpertStatus.SUCCESS,
                summary=str(state.get("agent_response", "")).strip() or f"{expert} 分析完成",
                result_data=result_data,
            ),
        )

    def _audit_research_results(self, state: Dict[str, Any]) -> None:
        """将确定性研究结果及其引用的原始快照单独写入可重放审计表。

        多标的一轮（比较、主题筛选）必须写成**同一次运行的多条结果**：
        ``save`` 会先删除该运行下的既有结果行，逐条调用只会留下最后一只。
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
        """把一轮多标的结论写成同一次研究运行。"""
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

    def _capture_task_facts(self, state: Dict[str, Any], task: Any) -> list[str]:
        """将本轮专家产出的业务输入登记为可引用的事实快照。"""
        domain = {
            "market_insight": "market",
            "stock_analysis": "market",
            "stock_recommendation": "market",
            "product_analysis": "product",
        }.get(task.intent.value if task.intent else "", "runtime")
        payload_keys = (
            "stock_data", "stock_analysis", "technical_analysis", "analysis_results", "theme_screening",
            "market_insight",
            "product_analysis",
        )
        payload = {key: state.get(key, {}) for key in payload_keys if state.get(key)}
        if not payload:
            return []
        fact_id = f"{task.task_id}-fact-1"
        facts = [fact for fact in state.get("facts", []) or [] if fact.fact_id != fact_id]
        facts.append(FactSnapshot(
            fact_id=fact_id,
            domain=domain,
            source=task.expert_name,
            fetched_at=datetime.now(timezone.utc),
            payload=payload,
        ))
        state["facts"] = facts
        evidence_ids: list[str] = []
        for result in state.get("analysis_results", []) or []:
            if not isinstance(result, dict):
                continue
            for evidence_id in result.get("evidence_ids", []) or []:
                if isinstance(evidence_id, str) and evidence_id:
                    evidence_ids.append(evidence_id)
        return list(dict.fromkeys([*evidence_ids, fact_id]))

    # 意图级状态 → 专家结果状态的映射。此前只识别 degraded，任何其它非 success
    # 文案（例如产品专家的 failed）都会被报成 SUCCESS，使崩溃看起来像成功。
    _INTENT_STATUS_TO_EXPERT = {
        "success": ExpertStatus.SUCCESS,
        "degraded": ExpertStatus.DEGRADED,
        # partial：市场洞察等专家"部分数据缺失但给出诚实降级说明"的中间态，
        # 审计上按 DEGRADED 记录，避免限制项被吞掉。
        "partial": ExpertStatus.DEGRADED,
        "failed": ExpertStatus.FAILED,
        "error": ExpertStatus.FAILED,
        "timeout": ExpertStatus.TIMEOUT,
        "blocked": ExpertStatus.FAILED,
        "cancelled": ExpertStatus.CANCELLED,
    }

    def _make_task_result(self, state: Dict[str, Any], task: Any, expert: str) -> ExpertResult:
        """从兼容专家状态构造严格的 task 级结果。"""
        intent = task.intent.value if task.intent else ""
        intent_result = (state.get("intent_results", {}) or {}).get(intent, {})
        status_name = str(intent_result.get("status", "success"))
        status = self._INTENT_STATUS_TO_EXPERT.get(status_name, ExpertStatus.SUCCESS)
        fact_ids = self._capture_task_facts(state, task)
        return ExpertResult(
            task_id=task.task_id,
            intent=task.intent,
            expert_name=expert,
            status=status,
            summary=str(intent_result.get("content", "")).strip()
            or str(state.get("agent_response", "")),
            result_data={
                key: state.get(key, {}) for key in (
                    "stock_data", "stock_analysis", "technical_analysis", "analysis_results",
                    "theme_screening",
                    "market_insight",
                    "product_analysis",
                ) if state.get(key)
            },
            fact_ids=fact_ids,
        )

    # 构建总管分派、专家执行、总管合成的状态图。
    def _build_graph(self) -> CompiledStateGraph:
        graph = StateGraph(AdvisorState)

        # 总管在单一节点完成意图识别和轻量需求委托。
        def manager_handler(state: AdvisorState) -> AdvisorState:
            self._trace_agent(state, "ManagerAgent")
            self._emit_progress("manager", "正在识别需求并分派专家")
            # 本轮起始清空上一轮遗留的澄清问题：它是 checkpoint 持久 channel，
            # 若不重置会短路本轮合成（专家已执行却被丢弃）。本轮若仍需澄清，
            # 下面的分支会重新写入。
            state["clarification_question"] = ""
            dispatch = self.manager.dispatch_tasks(state)
            state["task_dispatch"] = dispatch
            state["task_plan"] = list(dict.fromkeys(
                str(item["expert"]) for item in dispatch
            ))
            state["classification_error"] = state.get("classification_error", {}) or {}
            if state["classification_error"]:
                state.setdefault("warnings", []).append(
                    str(state["classification_error"].get("error_code", "intent_unavailable"))
                )
            # 澄清：无高置信度意图但有低置信度意图时，汇总澄清问题
            if not dispatch:
                uncertain = state.get("uncertain_intents", []) or []
                questions = [
                    str(item.get("clarification_question", "")).strip()
                    for item in uncertain
                    if isinstance(item, dict) and item.get("clarification_question")
                ]
                if questions:
                    state["clarification_question"] = "；".join(dict.fromkeys(questions))
            return state

        # 意图后置槽位提取：为每个意图抽取专家所需的结构化入参（名称→代码、否定、歧义、多轮合并）。
        def slot_handler(state: AdvisorState) -> AdvisorState:
            self._trace_agent(state, "SlotExtractor")
            self._emit_progress("slots", "正在提取专家所需的结构化参数")
            return self.slot_extractor.extract(state)

        def route_after_slots(state: AdvisorState) -> str:
            """有 task 走 DAG 批处理；无 task 直接进入合成（澄清或分类失败）。"""
            if state.get("tasks"):
                return "task_batch"
            return "manager_synthesis"

        def task_batch_handler(state: AdvisorState) -> AdvisorState:
            """按 task_id 执行全部任务的 DAG（含股票类）并合并结果。"""
            all_tasks = list(state.get("tasks", []) or [])
            agents = {
                name: agent for name, agent in (
                    ("stock_analysis", self.stock_agent),
                    ("market_insight", getattr(self, "market_insight_agent", None)),
                    ("product_analysis", self.product_agent),
                    ("casual_chat", self.casual_chat_agent),
                ) if agent is not None
            }
            local_states: dict[str, dict[str, Any]] = {}
            # 进度回调注册在**原始会话 thread_id** 上；工作线程里必须显式用它，
            # 否则 runner 里的进度事件全部被丢弃（thread-local 不跨线程）。
            progress_thread_id = str(state.get("thread_id", "") or "")

            def runner(task: Any, payload: dict[str, Any]) -> dict[str, Any]:
                local_state = copy.deepcopy(dict(state))
                local_state["thread_id"] = f"{state.get('thread_id', 'default')}:{task.task_id}"
                local_state["requirement"] = task.requirement
                local_state["current_task_intent"] = task.intent.value if task.intent else ""
                local_state["task_context"] = {
                    **build_task_context(state, task),
                    "upstream_results": payload.get("upstream_results", {}),
                }
                # 股票任务的逐标的取数进度需要回传，专家无状态、不能持有回调。
                local_state["progress_callback"] = (
                    lambda text, _stage=task.expert_name: self._emit_progress(
                        _stage, text, progress_thread_id,
                    )
                )
                agent = agents[task.expert_name]
                self._trace_agent(local_state, getattr(agent, "agent_name", task.expert_name))
                self._emit_progress(
                    task.expert_name, f"正在执行{task.expert_name}专家分析", progress_thread_id,
                )
                output = agent.invoke(local_state)
                local_states[task.task_id] = output
                return self._make_task_result(output, task, task.expert_name).model_dump(mode="json")

            results = run_task_dag(
                all_tasks,
                TaskContext(payload={}, runner=runner),
                max_retries=2,
                timeout_seconds=90,
                deadline_seconds=180,
                budgets=_DAG_BUDGETS,
            )
            state["task_results"] = results
            state["completed_tasks"] = []
            state["completed_experts"] = []
            for task in all_tasks:
                result = results.get(task.task_id)
                if result is None:
                    continue
                task.status = (
                    TaskStatus.SUCCESS
                    if result.status is ExpertStatus.SUCCESS
                    else TaskStatus.DEGRADED
                    if result.status is ExpertStatus.DEGRADED
                    else TaskStatus.BLOCKED
                    if result.error_code == "dependency_blocked"
                    else TaskStatus.TIMEOUT
                    if result.status is ExpertStatus.TIMEOUT
                    else TaskStatus.FAILED
                )
                task.retry_count = 0
                if result.error_code:
                    task.error_code = result.error_code
                self._audit_expert_result(state, task.expert_name, task)
                # 只合并成功/降级任务的本地产出：超时或失败的专家线程可能仍在
                # 运行，其迟到写入会污染共享状态与 agent_response。
                if task.task_id in local_states and result.status in (
                    ExpertStatus.SUCCESS, ExpertStatus.DEGRADED,
                ):
                    local = local_states[task.task_id]
                    for key in (
                        "user_profile", "stock_data", "stock_analysis", "technical_analysis",
                        "analysis_results",
                        "theme_screening",
                        "theme_screening_status", "theme_candidates", "pending_leads", "personalization_status",
                        "market_insight",
                        "product_analysis",
                        # 专家在本地状态里给出的澄清问题与运行级请求必须回传，
                        # 否则合成阶段读不到（旧扇出路径经专用错误键传递）。
                        "clarification_question", "research_request",
                    ):
                        value = local.get(key)
                        if not value:
                            continue
                        # 同一专家的多个任务并行执行时按 key 合并，避免 last-write-wins
                        # 丢掉另一任务的标的（例如同时"分析600519"与"推荐几只"）。
                        current = state.get(key)
                        if isinstance(current, dict) and isinstance(value, dict):
                            state[key] = merge_dict(current, value)
                        elif isinstance(current, list) and isinstance(value, list):
                            state[key] = dedupe_concat(current, value)
                        else:
                            state[key] = value
                    for intent, value in (local.get("intent_results", {}) or {}).items():
                        state.setdefault("intent_results", {})[intent] = value
                    if local.get("agent_response"):
                        # 单专家路径保留其文本；多任务时以合成为准。
                        state["agent_response"] = local["agent_response"]
                    for fact in local.get("facts", []) or []:
                        if fact.fact_id not in [item.fact_id for item in state["facts"]]:
                            state["facts"].append(fact)
                    state["completed_tasks"].append(task.task_id)
                    if task.expert_name not in state["completed_experts"]:
                        state["completed_experts"].append(task.expert_name)
                    if task.expert_name == "stock_analysis":
                        self._audit_research_results(local)
            if any(result.status is ExpertStatus.SUCCESS for result in results.values()):
                state["run_status"] = (
                    RunStatus.COMPLETED
                    if all(result.status is ExpertStatus.SUCCESS for result in results.values())
                    else RunStatus.PARTIAL
                )
            elif results:
                state["run_status"] = RunStatus.FAILED
            for task_id, result in results.items():
                if result.status is not ExpertStatus.SUCCESS:
                    state.setdefault("warnings", []).append(
                        f"{task_id}: {result.error_code or result.status.value}"
                    )
            return state

        # 总管合并各专家结果并附加统一风险提示。
        def synthesis_handler(state: AdvisorState) -> AdvisorState:
            self._trace_agent(state, "ManagerAgent.synthesis")
            if self._is_stopped(str(state.get("thread_id", ""))):
                state["cancelled"] = True
                state["agent_response"] = "已停止生成，当前已完成的专家结果已保留。"
                return state
            question = str(state.get("clarification_question", "")).strip()
            if question:
                state["agent_response"] = f"需要您进一步确认：{question}"
                # 澄清轮次已成功产出反问，给终态，避免审计把它记成仍在运行。
                state["run_status"] = RunStatus.COMPLETED
                return state
            classification_error = state.get("classification_error", {}) or {}
            if classification_error:
                state["run_status"] = RunStatus.FAILED
                state["agent_response"] = (
                    "暂时无法确认您的需求，请稍后重试或更具体地描述要分析的股票、产品或配置目标。"
                )
                return state
            self._emit_progress("manager", "正在综合专家分析结果")
            state["agent_response"] = self.manager.synthesize_response(state)
            return state

        graph.add_node("manager", manager_handler)
        graph.add_node("slot_extraction", slot_handler)
        graph.add_node("task_batch", task_batch_handler)
        graph.add_node("manager_synthesis", synthesis_handler)
        graph.add_edge(START, "manager")
        graph.add_edge("manager", "slot_extraction")
        graph.add_conditional_edges(
            "slot_extraction", route_after_slots, ["task_batch", "manager_synthesis"],
        )
        graph.add_edge("task_batch", "manager_synthesis")
        graph.add_edge("manager_synthesis", END)
        return graph.compile(checkpointer=self.checkpointer)

    # 更新对话元数据，失败时不影响主流程。
    def _update_conversation_meta(self, conversation_id: str, message: str, customer_id: str) -> None:
        try:
            db = get_database()
            if db.get_conversation(conversation_id, customer_id):
                db.rename_conversation_from_message(conversation_id, message)
            else:
                title = " ".join(message.strip().split())[:28] or "新对话"
                db.create_conversation(customer_id, title, conversation_id=conversation_id)
        except Exception:
            pass

    def _v2_failed_output(self, conversation_id: str, message: str) -> Dict[str, Any]:
        """V2 异常时的安全失败响应；绝不回退旧路径。"""
        return {
            "response": "处理请求时发生内部错误，请稍后重试。",
            "task_plan": [],
            "task_dispatch": [],
            "tasks": [],
            "task_results": {},
            "run_status": "failed",
            "warnings": ["v2_execution_failed"],
            "conversation_id": conversation_id or uuid.uuid4().hex,
        }

    # 处理一轮消息，按功能开关选择 V2 根图或旧路径。
    def handle_message(self, message, chat_history=None, customer_id="CUST001", progress_callback=None, conversation_id=""):
        if getattr(self, "_orchestration_v2", False):
            return self.handle_message_v2(
                message,
                chat_history=chat_history,
                customer_id=customer_id,
                progress_callback=progress_callback,
                conversation_id=conversation_id,
            )
        return self._handle_message_legacy(
            message,
            chat_history=chat_history,
            customer_id=customer_id,
            progress_callback=progress_callback,
            conversation_id=conversation_id,
        )

    # V2：根图为唯一执行路径；任何异常显式失败，不回退旧路径。
    def handle_message_v2(
        self,
        message: str,
        chat_history: List[Dict[str, str]] | None = None,
        customer_id: str = "CUST001",
        progress_callback: Callable[[str, str], None] | None = None,
        conversation_id: str = "",
    ) -> Dict[str, Any]:
        conversation_id = conversation_id or uuid.uuid4().hex
        if find_sensitive_word(message) is not None:
            return {
                "response": BLOCKED_RESPONSE,
                "task_plan": [],
                "task_dispatch": [],
                "tasks": [],
                "task_results": {},
                "run_status": "completed",
                "warnings": [],
                "conversation_id": conversation_id,
                "compliance_result": {},
                "blocked": True,
            }

        # 与旧路径一致的停止语义：进入新一轮时清除上轮停止标记。
        with self._stop_lock:
            self._stop_requests.pop(conversation_id, None)
        if progress_callback is not None:
            with self._progress_lock:
                self._progress_callbacks[conversation_id] = progress_callback
        self._progress_context.callback = progress_callback
        self._emit_progress("manager", "正在识别业务领域", conversation_id)

        fallback_history = chat_history or self.get_checkpoint_conversation_messages(
            conversation_id, self.memory.window_size,
        )
        identifiers = generate_identifiers(conversation_id)
        run_id = str(identifiers.run_id)
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
            memory_data = self.memory.load_context(customer_id, conversation_id, fallback_history)
            history = memory_data.get("sliding_window") or fallback_history[-self.memory.window_size:]
            root = getattr(self, "_v2_root", None) or self._build_v2_root()
            result = root.invoke(
                {
                    "user_message": message,
                    "history": "\n".join(
                        str(item.get("content", "")) for item in history if isinstance(item, dict)
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
            logger.exception("orchestration_v2_failed conversation_id=%s", conversation_id)
            output = self._v2_failed_output(conversation_id, message)
        else:
            output = project_root_state(result, conversation_id=conversation_id)
            output["customer_id"] = customer_id

        self._v2_persist(customer_id, conversation_id, message, output)
        return output

    # V2 运行后的会话落库与记忆更新（失败静默，保持与旧路径一致）。
    def _v2_persist(
        self, customer_id: str, conversation_id: str, message: str, output: Dict[str, Any],
    ) -> None:
        try:
            self.audit.complete_run(
                str(uuid.uuid4()), conversation_id, output.get("response", ""),
                message_id=str(uuid.uuid4()), status=output.get("run_status", "completed"),
                metadata={"task_plan": output.get("task_plan", [])},
            )
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

    # 处理一轮同步消息，保持既有公共签名（旧路径）。
    def _handle_message_legacy(
        self,
        message: str,
        chat_history: List[Dict[str, str]] | None = None,
        customer_id: str = "CUST001",
        progress_callback: Callable[[str, str], None] | None = None,
        conversation_id: str = "",
    ) -> Dict[str, Any]:
        with self._workflow_lock:
            if find_sensitive_word(message) is not None:
                return {
                    "response": BLOCKED_RESPONSE, "task_plan": [],
                    "task_dispatch": [], "user_profile": {}, "stock_data": {},
                    "stock_analysis": {}, "market_insight": {},
                    "product_analysis": {},
                    "compliance_result": {}, "conversation_id": conversation_id or uuid.uuid4().hex,
                    "blocked": True,
                }
            conversation_id = conversation_id or uuid.uuid4().hex
            with self._stop_lock:
                self._stop_requests.pop(conversation_id, None)
            config = {"configurable": {"thread_id": conversation_id}}
            fallback_history = chat_history or self.get_checkpoint_conversation_messages(
                conversation_id, self.memory.window_size,
            )
            memory_data = self.memory.load_context(customer_id, conversation_id, fallback_history)
            history = memory_data.get("sliding_window") or fallback_history[-self.memory.window_size:]
            identifiers = generate_identifiers(conversation_id)
            run_id = str(identifiers.run_id)
            trace_id = str(identifiers.trace_id)
            message_id = str(identifiers.message_id)
            with self._stop_lock:
                self._active_runs[run_id] = conversation_id
            # 可选审计：创建运行记录（未配置 PostgreSQL 时为 no-op）
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
            state: AdvisorState = {
                "user_message": message, "chat_history": history, "customer_id": customer_id,
                "task_plan": [], "task_dispatch": [], "completed_experts": [],
                "tasks": [], "completed_tasks": [], "task_results": {}, "run_status": RunStatus.RUNNING,
                "warnings": [], "facts": [],
                "business_state": {}, "user_profile": memory_data.get("profile", {}) or {},
                "stock_data": {}, "stock_analysis": {}, "technical_analysis": {},
                "theme_screening": {}, "theme_screening_status": "", "theme_candidates": [],
                "pending_leads": [], "personalization_status": "",
                "product_analysis": {},
                "market_insight": {},
                "intent_results": {}, "detected_intents": [], "finance_related": True,
                "agent_response": "", "compliance_result": {},
                # 澄清问题是 checkpoint 持久 channel，会跨轮沿用；若不在每轮起始
                # 重置，上一轮的反问会短路本轮合成（专家已执行却被丢弃）。本轮
                # 若仍需澄清，manager/slot 节点会重新写入。
                "clarification_question": "",
                "research_request": {},
                "memory_context": memory_data.get("context_text", ""),
                "thread_id": conversation_id, "run_id": run_id,
                "trace_id": trace_id, "message_id": message_id,
                "explicit_user_stock_codes": [], "uncertain_intents": [],
            }
            # 跨轮槽位合并/更新：不必在此显式回填 intent_slots——
            # LangGraph 会按 thread_id 保留上一轮的 channel 值（新输入的
            # 字段覆盖、未提供的字段沿用 checkpoint），因此槽位层能读到上一轮的槽位。
            if progress_callback:
                with self._progress_lock:
                    self._progress_callbacks[conversation_id] = progress_callback
            self._progress_context.callback = progress_callback
            self._trace_sequences[conversation_id] = 0
            try:
                result = self.graph.invoke(state, config=config)
            finally:
                self._progress_context.callback = None
                with self._progress_lock:
                    self._progress_callbacks.pop(conversation_id, None)
                self._trace_sequences.pop(conversation_id, None)
                with self._stop_lock:
                    self._active_runs.pop(run_id, None)
                    self._stop_requests.pop(conversation_id, None)
            output = {
                "response": result.get("agent_response", ""),
                "task_plan": result.get("task_plan", []),
                "task_dispatch": result.get("task_dispatch", []),
                "tasks": [task.model_dump(mode="json") for task in result.get("tasks", [])],
                "task_results": {
                    task_id: value.model_dump(mode="json") if hasattr(value, "model_dump") else value
                    for task_id, value in (result.get("task_results", {}) or {}).items()
                },
                "run_status": result.get("run_status", RunStatus.COMPLETED).value
                if hasattr(result.get("run_status", RunStatus.COMPLETED), "value")
                else result.get("run_status", "completed"),
                "warnings": result.get("warnings", []),
                "facts": [fact.model_dump(mode="json") for fact in result.get("facts", [])],
                "user_profile": result.get("user_profile", {}),
                "stock_data": result.get("stock_data", {}),
                "stock_analysis": result.get("stock_analysis", {}),
                "technical_analysis": result.get("technical_analysis", {}),
                "fundamental_analysis": result.get("fundamental_analysis", {}),
                "analysis_results": result.get("analysis_results", []),
                "theme_screening": result.get("theme_screening", {}),
                "theme_screening_status": result.get("theme_screening_status", ""),
                "theme_candidates": result.get("theme_candidates", []),
                "pending_leads": result.get("pending_leads", []),
                "personalization_status": result.get("personalization_status", ""),
                "product_analysis": result.get("product_analysis", {}),
                "market_insight": result.get("market_insight", {}),
                "compliance_result": result.get("compliance_result", {}),
                "explicit_user_stock_codes": result.get("explicit_user_stock_codes", []),
                "conversation_id": conversation_id,
            }
            # 可选审计：完成运行记录（保留已提交的专家结果）
            self.audit.complete_run(
                run_id, conversation_id, output["response"],
                message_id=str(uuid.uuid4()),
                status="cancelled" if result.get("cancelled") else output["run_status"],
                metadata={"task_plan": output["task_plan"]},
            )
            self._update_conversation_meta(conversation_id, message, customer_id)
            try:
                db = get_database()
                db.append_conversation_message(conversation_id, "user", message)
                db.append_conversation_message(conversation_id, "assistant", output["response"], {"task_plan": output["task_plan"]})
            except Exception:
                pass
            self.memory.append_window_message(conversation_id, "user", message)
            self.memory.append_window_message(conversation_id, "assistant", output["response"], {"task_plan": output["task_plan"]})
            self.memory.update_profile_from_result(customer_id, message, output)
            self.memory.update_recent_summary(conversation_id, [{"role": "user", "content": message}, {"role": "assistant", "content": output["response"], "metadata": output}])
            return output

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
            yield {"type": "stage", "stage": "manager", "message": "正在选择需要执行的专家..."}
        loop = asyncio.get_running_loop()
        progress_queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()

        # 将同步进度回调安全投递到异步队列。
        def report(stage: str, text: str) -> None:
            loop.call_soon_threadsafe(progress_queue.put_nowait, {"type": "stage", "stage": stage, "message": text})

        task = asyncio.create_task(asyncio.to_thread(self.handle_message, message, chat_history, customer_id, report, conversation_id))
        while not task.done() or not progress_queue.empty():
            try:
                yield await asyncio.wait_for(progress_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                yield {"type": "heartbeat"}
        result = await task
        yield {"type": "response", "content": result["response"], "data": result}

    # 查询历史会话列表。
    def list_checkpoint_conversations(self, customer_id: str) -> list[dict[str, Any]]:
        try:
            return get_database().list_conversations(customer_id)
        except Exception:
            return []

    # 查询指定会话消息。
    def get_checkpoint_conversation_messages(self, conversation_id: str, limit: int = 100) -> list[dict[str, Any]]:
        try:
            return get_database().get_conversation_messages(conversation_id, limit)
        except Exception:
            return []

    # 删除会话数据库、checkpoint 和记忆数据。
    def delete_checkpoint_conversation(self, conversation_id: str, customer_id: str) -> bool:
        try:
            get_database().delete_conversation(conversation_id, customer_id)
            delete = getattr(self.checkpointer, "delete_thread", None)
            if callable(delete):
                delete(conversation_id)
            else:
                conn = self.checkpointer.conn
                conn.execute("DELETE FROM writes WHERE thread_id = ?", (conversation_id,))
                conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", (conversation_id,))
                conn.commit()
            self.memory.store.clear_conversation(conversation_id)
            return True
        except Exception:
            return False

    # 清除用户画像并返回清除数量。
    def clear_profile(self, customer_id: str | None = None) -> int:
        try:
            return get_database().delete_profiles(customer_id) if customer_id else get_database().delete_profiles()
        except Exception:
            return 0

    # 重置客户所有会话的短期记忆（滑动窗口 + 摘要），返回清除数量。
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

    # 获取用户画像。
    def get_user_profile(self, customer_id: str) -> Dict[str, Any]:
        from dataclasses import asdict
        return asdict(self.memory.get_profile(customer_id))
