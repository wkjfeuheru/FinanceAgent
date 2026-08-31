"""金融投顾总管-专家编排系统。"""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from typing import Any, Callable, Dict, List

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from finance_agent.agents.asset_allocation import AssetAllocationAgent
from finance_agent.agents.casual_chat import CasualChatAgent
from finance_agent.agents.product_analysis import ProductAnalysisAgent
from finance_agent.agents.stock_analysis import StockAnalysisAgent
from finance_agent.agents.supervisor import ManagerAgent
from finance_agent.config import get_checkpoint_saver
from finance_agent.contracts import (
    ExpertResult,
    ExpertStatus,
    RequestEnvelope,
    generate_identifiers,
)
from finance_agent.data.postgres_repository import PostgresAuditStore
from finance_agent.orchestrator.database import get_database
from finance_agent.orchestrator.memory import AgentMemoryContext, RedisMemoryStore
from finance_agent.orchestrator.state import AdvisorState
from finance_agent.middleware import BLOCKED_RESPONSE, find_sensitive_word

logger = logging.getLogger(__name__)


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
        self.allocation_agent = AssetAllocationAgent()
        self.product_agent = ProductAnalysisAgent(checkpointer=self.checkpointer)
        self.casual_chat_agent = CasualChatAgent()
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

    # 向当前请求注册并发送阶段进度。
    def _emit_progress(self, stage: str, message: str, thread_id: str = "") -> None:
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
    def _audit_expert_result(self, state: Dict[str, Any], expert: str) -> None:
        if not self.audit.is_available():
            return
        run_id = str(state.get("run_id", "") or "")
        trace_id = str(state.get("trace_id", "") or "")
        if not run_id:
            return
        if expert == "stock_analysis":
            result_data = {
                "stock_data": state.get("stock_data", {}),
                "stock_analysis": state.get("stock_analysis", {}),
                "technical_analysis": state.get("technical_analysis", {}),
            }
        elif expert == "asset_allocation":
            result_data = {
                "allocation_result": state.get("allocation_result", {}),
                "debate_result": state.get("debate_result", {}),
            }
        elif expert == "product_analysis":
            result_data = {"product_analysis": state.get("product_analysis", {})}
        else:
            result_data = state.get("intent_results", {}).get("casual_chat", {})
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

    # 构建总管分派、专家执行、总管合成的状态图。
    def _build_graph(self) -> CompiledStateGraph:
        graph = StateGraph(AdvisorState)
        experts = {
            "stock_analysis": (self.stock_agent, "stock_analysis"),
            "asset_allocation": (self.allocation_agent, "asset_allocation"),
            "product_analysis": (self.product_agent, "product_analysis"),
            "casual_chat": (self.casual_chat_agent, "casual_chat"),
        }

        # 总管在单一节点完成意图识别和轻量需求委托。
        def manager_handler(state: AdvisorState) -> AdvisorState:
            self._trace_agent(state, "ManagerAgent")
            self._emit_progress("manager", "正在识别需求并分派专家")
            dispatch = self.manager.dispatch_tasks(state)
            state["task_dispatch"] = dispatch
            state["task_plan"] = list(dict.fromkeys(
                str(item["expert"]) for item in dispatch
            ))
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

        # 从委托列表中选择尚未执行的专家。
        def route_expert(state: AdvisorState) -> str:
            if self._is_stopped(str(state.get("thread_id", ""))):
                return "manager_synthesis"
            completed = set(state.get("completed_experts", []))
            for item in state.get("task_dispatch", []):
                expert = str(item.get("expert", ""))
                if expert in experts and expert not in completed:
                    return expert
            return "manager_synthesis"

        # 将完整 AdvisorState 和独立需求传给指定专家。
        def expert_handler(expert: str) -> Callable[[AdvisorState], AdvisorState]:
            agent, stage = experts[expert]

            # 执行单个专家委托并记录结果。
            def handle(state: AdvisorState) -> AdvisorState:
                requirement = next(
                    (item.get("requirement", "")
                     for item in state.get("task_dispatch", [])
                     if item.get("expert") == expert),
                    state.get("user_message", ""),
                )
                state["requirement"] = str(requirement)
                self._trace_agent(state, getattr(agent, "agent_name", expert))
                self._emit_progress(stage, f"正在执行{stage}专家分析")
                if expert == "asset_allocation":
                    self._emit_progress("debate", "正在进行资产配置多空辩论")
                result = agent.invoke(state)
                completed = list(result.get("completed_experts", []))
                if expert not in completed:
                    completed.append(expert)
                result["completed_experts"] = completed
                self._audit_expert_result(result, expert)
                return result

            return handle

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
                return state
            self._emit_progress("manager", "正在综合专家分析结果")
            state["agent_response"] = self.manager.synthesize_response(state)
            return state

        graph.add_node("manager", manager_handler)
        for expert in experts:
            graph.add_node(expert, expert_handler(expert))
        graph.add_node("manager_synthesis", synthesis_handler)
        graph.add_edge(START, "manager")
        targets = list(experts) + ["manager_synthesis"]
        graph.add_conditional_edges("manager", route_expert, targets)
        for expert in experts:
            graph.add_conditional_edges(expert, route_expert, targets)
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

    # 处理一轮同步消息，保持既有公共签名。
    def handle_message(
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
                    "stock_analysis": {}, "allocation_result": {},
                    "debate_result": {}, "product_analysis": {},
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
                "business_state": {}, "user_profile": memory_data.get("profile", {}) or {},
                "stock_data": {}, "stock_analysis": {}, "technical_analysis": {},
                "allocation_result": {}, "debate_result": {}, "product_analysis": {},
                "intent_results": {}, "detected_intents": [], "finance_related": True,
                "agent_response": "", "compliance_result": {},
                "memory_context": memory_data.get("context_text", ""),
                "thread_id": conversation_id, "run_id": run_id,
                "trace_id": trace_id, "message_id": message_id,
                "explicit_user_stock_codes": [], "uncertain_intents": [],
            }
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
                "user_profile": result.get("user_profile", {}),
                "stock_data": result.get("stock_data", {}),
                "stock_analysis": result.get("stock_analysis", {}),
                "allocation_result": result.get("allocation_result", {}),
                "debate_result": result.get("debate_result", {}),
                "product_analysis": result.get("product_analysis", {}),
                "compliance_result": result.get("compliance_result", {}),
                "explicit_user_stock_codes": result.get("explicit_user_stock_codes", []),
                "conversation_id": conversation_id,
            }
            # 可选审计：完成运行记录（保留已提交的专家结果）
            self.audit.complete_run(
                run_id, conversation_id, output["response"],
                message_id=str(uuid.uuid4()),
                status="cancelled" if result.get("cancelled") else "completed",
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
