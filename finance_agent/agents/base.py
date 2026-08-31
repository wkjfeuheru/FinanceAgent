"""
1. 使用 LangGraph 的 create_react_agent 实现显式多步推理
2. 每个 Agent 拥有独立的 MemorySaver 支持会话内状态持久化
3. 通过 AdvisorState 显式传递 Agent 间信息
4. 支持流式输出接口（astream_events）
5. 内置自我反思（Reflection）循环
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List

from langchain.agents import create_agent
from langgraph.graph.state import CompiledStateGraph

from finance_agent.config import get_model_for_agent
from finance_agent.middleware import content_filter, model_retry


# ── New Agent base classes (Task 3) ────────────────────────────────

class AgentProtocol:
    """Agent 抽象协议 —— 所有 Agent 必须实现 invoke(state)。"""

    agent_name: str = "base"

    def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError(
            f"{self.__class__.__name__} 必须实现 invoke(state) 方法"
        )


class ProceduralAgent(AgentProtocol):
    """过程式 Agent —— 无 LLM 循环，用于简单的数据获取/预处理。"""

    agent_name: str = "procedural"

    def __init__(self, **_: Any):
        pass

    def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        return state

    def _build_effective_message(
        self,
        message: str,
        customer_id: str = "",
        memory_context: str = "",
    ) -> str:
        """构建发送给 Agent 的有效消息。"""
        parts: list[str] = []

        if customer_id:
            parts.append(f"当前客户号：{customer_id}")

        if memory_context:
            parts.append(memory_context)

        parts.append(f"用户问题：{message}")

        return "\n\n".join(parts)


class ReActAgent(AgentProtocol):
    """ReAct Agent —— 多步推理循环，内置超时/安全/健康检测。

    子类覆盖 _get_tools() 和 _get_system_prompt() 即可定制行为。
    """

    agent_name: str = "react"
    max_reasoning_steps: int = 10
    max_tool_calls_per_step: int = 2
    per_invoke_timeout: float = 90.0
    tool_call_same_param_limit: int = 3
    tool_call_history_window: int = 6

    def __init__(self, checkpointer=None):
        self._agent: CompiledStateGraph | None = None
        self._memory_saver = checkpointer

    def _get_tools(self) -> list:
        return []

    def _get_system_prompt(self) -> str:
        return "你是一个金融客服系统的专业 Agent。"

    def _fallback(self, state: Dict[str, Any], reason: str) -> Dict[str, Any]:
        state["agent_response"] = f"分析暂时不可用：{reason}"
        return state

    def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        result_container: list = []
        error_container: list[Exception | None] = [None]
        done = threading.Event()

        def _run():
            try:
                result_container.append(self._invoke_internal(state))
            except RecursionError:
                error_container[0] = RecursionError("推理步数超限")
            except Exception as exc:
                error_container[0] = exc
            finally:
                done.set()

        thread = threading.Thread(
            target=_run,
            daemon=True,
            name=f"react-{self.agent_name}",
        )
        thread.start()

        if not done.wait(timeout=self.per_invoke_timeout):
            return self._fallback(
                state,
                f"ReAct invoke 超时（{self.per_invoke_timeout}s）",
            )

        if error_container[0] is not None:
            return self._fallback(state, str(error_container[0]))

        return result_container[0]

    def _invoke_internal(self, state: Dict[str, Any]) -> Dict[str, Any]:
        messages = [{"role": "user", "content": state.get("user_message", "")}]
        config = {
            "configurable": {"thread_id": state.get("thread_id", "default")},
            "recursion_limit": self.max_reasoning_steps * 2 + 3,
        }
        result = self.agent.invoke({"messages": messages}, config=config)
        final_msg = result.get("messages", [{}])[-1]
        state["agent_response"] = (
            final_msg.content if hasattr(final_msg, "content") else str(final_msg)
        )
        return state

    def _check_tool_call_health(
        self,
        tool_calls: List[Dict[str, Any]],
        call_history: List[Dict[str, Any]],
    ) -> str | None:
        """检测最近工具调用中的异常模式。

        返回 str 表示检测到问题，返回 None 表示健康。
        """
        recent = call_history[-self.tool_call_history_window :]

        # 1. 无进展检测：连续 3 次完全相同（优先检测，是更具体的模式）
        if len(recent) >= 3:
            last3 = [
                (h["name"], frozenset(h.get("args", {}).items()))
                for h in recent[-3:]
            ]
            if len(set(last3)) == 1:
                return "连续 3 次工具调用完全相同，无进展"

        # 2. 交替循环检测：A→B→A→B 模式
        if len(recent) >= 4:
            last4 = [
                (h["name"], frozenset(h.get("args", {}).items()))
                for h in recent[-4:]
            ]
            if (
                last4[0] == last4[2]
                and last4[1] == last4[3]
                and last4[0] != last4[1]
            ):
                return "检测到工具交替循环调用"

        # 3. 相同参数重复调用检测（窗口内任意位置 ≥ limit 次）
        for tc in tool_calls:
            sig = (tc["name"], frozenset(tc.get("args", {}).items()))
            count = sum(
                1
                for h in recent
                if (h["name"], frozenset(h.get("args", {}).items())) == sig
            )
            if count >= self.tool_call_same_param_limit:
                return (
                    f"工具 {tc['name']} 以相同参数被重复调用 {count} 次，"
                    f"疑似死循环，已停止重复调用"
                )

        return None

    @property
    def agent(self) -> CompiledStateGraph:
        if self._agent is None:
            self._agent = create_agent(
                model=get_model_for_agent(self.agent_name),
                tools=self._get_tools(),
                system_prompt=self._get_system_prompt(),
                name=self.agent_name,
                checkpointer=self._memory_saver,
                middleware=[model_retry, content_filter],
            )
        return self._agent

