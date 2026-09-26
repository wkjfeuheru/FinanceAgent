"""同步用户轮次的生命周期与 LangGraph 调用编排。"""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict
from typing import Any, Callable, Dict, List, Protocol

from finance_agent.shared.contracts import RequestEnvelope
from finance_agent.shared.identifiers import generate_identifiers
from finance_agent.orchestration.budgets import RunBudgets
from finance_agent.orchestration.runtime.state import run_of
from finance_agent.orchestration.runtime.thread_key import build_thread_id
from finance_agent.orchestration.graphs.supervisor import (
    project_interrupt_state,
    project_supervisor_state,
)
from finance_agent.safety.input_policy import (
    BLOCKED_RESPONSE,
    TRADE_REJECTED_RESPONSE,
    is_trade_request,
    should_block_input,
)

logger = logging.getLogger(__name__)

#: 滑动窗口消息的角色标签。分类器（``context_summary``）与任务改写器（``history``）
#: 读到的是**同一份**文本，且必须能区分"用户说过什么"与"助手上一轮答过什么"：
#: 只拼 content 会让延续性追问（"我是稳健型选手，你有什么建议？"）的指代无法还原，
#: 分类器也就只能给出低置信度、退化成一句与上下文无关的固定澄清。
_ROLE_LABELS = {"user": "用户", "assistant": "助手"}
#: 历史文本的默认字符上限；宿主 memory 未声明上下文预算时用它兜底。
DEFAULT_HISTORY_CHARS = 6000


def _history_text(
    messages: list[dict[str, Any]] | None,
    limit: int = DEFAULT_HISTORY_CHARS,
) -> str:
    """把滑动窗口渲染为带角色标签的历史文本，并按上限保留**最新**内容。"""
    lines: list[str] = []
    for item in messages or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "") or "").strip().lower()
        label = _ROLE_LABELS.get(role, role or "消息")
        content = str(item.get("content", "") or "").strip()
        if content:
            lines.append(f"{label}: {content}")
    text = "\n".join(lines)
    if limit <= 0 or len(text) <= limit:
        return text
    return text[-limit:]


def stable_user_id(customer_id: str) -> uuid.UUID:
    """从客户标识派生稳定 UUID，供审计按用户维度聚合。"""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"finance-agent:customer:{customer_id}")


class _Host(Protocol):
    memory: Any
    audit: Any

    def _conversation_guard(self, conversation_id: str): ...
    def _emit_progress(self, stage: str, message: str, conversation_id: str = "") -> None: ...
    def _best_effort(self, category: str, action: Callable[[], Any]) -> None: ...
    def _best_effort_value(self, category: str, action: Callable[[], Any]) -> Any: ...
    def _persist_param_profile(
        self, customer_id: str, answers: Dict[str, Any] | None,
        profile_payload: Dict[str, Any],
    ) -> None: ...
    def _invoke_with_resume(
        self, root: Any, config: Dict[str, Any], *, resume: bool,
        answers: Dict[str, Any] | None, base_input: Dict[str, Any],
    ) -> Dict[str, Any]: ...
    def _persist_pending_outcomes(
        self, state: Dict[str, Any], *, customer_id: str, conversation_id: str,
    ) -> None: ...
    def _build_supervisor(self) -> Any: ...
    def _trace_agent(self, name: str, conversation_id: str = "UNKNOWN") -> None: ...
    def _failed_output(self, conversation_id: str) -> Dict[str, Any]: ...
    def _persist(
        self, customer_id: str, conversation_id: str, message: str,
        output: Dict[str, Any], run_id: str,
        model_facts: List[Dict[str, Any]] | None = None,
    ) -> None: ...
    def get_checkpoint_conversation_messages(
        self, conversation_id: str, limit: int = 100,
    ) -> List[Dict[str, Any]]: ...


class TurnCoordinator:
    """单轮同步执行流程；运行时协作通过宿主接口动态解析。"""

    def __init__(self, host: _Host) -> None:
        self._host = host

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
        """执行一轮同步消息，保留 AdvisorSystem 的原有状态与注入接缝。"""
        host = self._host
        conversation_id = conversation_id or uuid.uuid4().hex
        if should_block_input(message):
            return {
                "response": BLOCKED_RESPONSE,
                "task_plan": [], "task_dispatch": [], "tasks": [], "task_results": {},
                "run_status": "completed", "warnings": [],
                "conversation_id": conversation_id,
                "compliance_result": {}, "blocked": True,
            }
        if is_trade_request(message):
            return {
                "response": TRADE_REJECTED_RESPONSE,
                "task_plan": [], "task_dispatch": [], "tasks": [], "task_results": {},
                "run_status": "completed", "warnings": ["trade_request_rejected"],
                "conversation_id": conversation_id,
                "compliance_result": {}, "blocked": True,
            }

        with host._conversation_guard(conversation_id):
            with host._stop_lock:
                host._stop_requests.pop(conversation_id, None)
            if progress_callback is not None:
                with host._progress_lock:
                    host._progress_callbacks[conversation_id] = progress_callback
            host._progress_context.callback = progress_callback
            host._stop_context_ref.conversation_id = conversation_id
            host._trace_sequences[conversation_id] = 0
            host._emit_progress("manager", "正在识别业务领域", conversation_id)

            fallback_history = chat_history or host.get_checkpoint_conversation_messages(
                conversation_id, host.memory.window_size,
            )
            identifiers = generate_identifiers(conversation_id)
            run_id = str(identifiers.run_id)
            with host._stop_lock:
                host._active_runs[run_id] = (conversation_id, customer_id)
            host._best_effort(
                "audit_create_run",
                lambda: host.audit.create_run(
                    RequestEnvelope(
                        run_id=identifiers.run_id,
                        trace_id=identifiers.trace_id,
                        user_id=stable_user_id(customer_id),
                        customer_id=customer_id,
                        conversation_id=conversation_id,
                        message_id=identifiers.message_id,
                        message=message,
                    )
                ),
            )

            try:
                model_facts: list[dict[str, Any]] = []
                memory_data = host.memory.load_context(
                    customer_id, conversation_id, fallback_history,
                )
                history = memory_data.get("sliding_window") or fallback_history[-host.memory.window_size:]
                # 历史文本统一在这里生成（带角色标签 + 尾部限长）：分类器与任务
                # 改写器读到的必须是同一份文本。``sliding_window_text`` 只在结构化
                # 窗口为空时兜底（它没有长度上限，不能直接当图输入）。
                history_text = _history_text(
                    list(history),
                    int(getattr(host.memory, "max_context_chars", 0) or DEFAULT_HISTORY_CHARS),
                ) or str(memory_data.get("sliding_window_text") or "")
                root = getattr(host, "supervisor", None) or host._build_supervisor()
                host._trace_agent("RootGraph", conversation_id)
                thread_id = build_thread_id(customer_id, conversation_id)
                profile_card = host._best_effort_value(
                    "load_profile", lambda: host.memory.get_profile(customer_id),
                )
                profile_payload = asdict(profile_card) if profile_card is not None else {}
                host._persist_param_profile(customer_id, answers, profile_payload)
                config = {
                    "configurable": {"thread_id": thread_id},
                    "recursion_limit": getattr(
                        host, "budgets", RunBudgets.from_config(),
                    ).graph_steps,
                }
                result = host._invoke_with_resume(
                    root, config, resume=resume, answers=answers,
                    base_input={
                        "user_message": message,
                        "history": history_text,
                        "customer_id": customer_id,
                        "conversation_id": conversation_id,
                        "thread_id": thread_id,
                        "run_id": run_id,
                        "user_profile": profile_payload,
                    },
                )
            except Exception:
                logger.exception("orchestration_failed conversation_id=%s", conversation_id)
                output = host._failed_output(conversation_id)
            else:
                if result.get("__interrupt__"):
                    output = project_interrupt_state(
                        result, conversation_id=conversation_id, customer_id=customer_id,
                    )
                else:
                    output = project_supervisor_state(result, conversation_id=conversation_id)
                    output["customer_id"] = customer_id
                    host._persist_pending_outcomes(
                        result, customer_id=customer_id, conversation_id=conversation_id,
                    )
                # 本轮用户**自述**事实的候选随路由决策一路带出（分类器同一次调用
                # 产出）。它们只经内存对象透传：不进 API 响应契约，也不改投影。
                model_facts = [
                    dict(fact)
                    for fact in (run_of(result).get("routing") or {}).get("profile_facts") or []
                    if isinstance(fact, dict)
                ]
            finally:
                host._progress_context.callback = None
                host._stop_context_ref.conversation_id = ""
                with host._progress_lock:
                    host._progress_callbacks.pop(conversation_id, None)
                host._trace_sequences.pop(conversation_id, None)
                with host._stop_lock:
                    host._active_runs.pop(run_id, None)
                    host._stop_requests.pop(conversation_id, None)
                host._persist(
                    customer_id, conversation_id, message, output, run_id,
                    model_facts=model_facts,
                )

        return output
