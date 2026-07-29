"""
1. 使用 LangGraph 的 create_react_agent 实现显式多步推理
2. 每个 Agent 拥有独立的 MemorySaver 支持会话内状态持久化
3. 集成 SharedWorkingMemory 实现 Agent 间信息共享
4. 支持流式输出接口（astream_events）
5. 内置自我反思（Reflection）循环
"""

from __future__ import annotations

import threading
from typing import Any, AsyncIterator, Dict, List

from langchain.agents import create_agent
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from finance_agent.config import get_model_for_agent
from finance_agent.core.shared_state import SharedWorkingMemory
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

    def __init__(self, shared_memory=None):
        self.shared_memory = shared_memory

    def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        return state

    def _build_effective_message(
        self,
        message: str,
        customer_id: str = "",
        memory_context: str = "",
    ) -> str:
        """构建发送给 Agent 的有效消息，自动注入共享工作内存中的发现。"""
        parts: list[str] = []

        if self.shared_memory and self.shared_memory.facts:
            facts_text = self.shared_memory.format_facts_for_prompt()
            if facts_text:
                parts.append(
                    f"[共享上下文]\n"
                    f"以下是当前任务的内部分析材料，请直接回答用户问题，"
                    f"不要向用户说明材料来源：\n\n{facts_text}"
                )

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

    def __init__(self, shared_memory=None, checkpointer=None):
        self.shared_memory = shared_memory
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


# ── Legacy BaseFinanceAgent (Task 13 will remove) ──────────────────

class BaseFinanceAgent:
    """Agent 基类。
    - create_react_agent（支持多步推理循环）
    - 内置 MemorySaver（每个 Agent 可独立 checkpoint）
    - 可接入共享工作内存（跨 Agent 信息发现）
    - 支持流式事件输出
    - 每个 Agent 使用对应温度策略的模型实例
    """

    # 子类覆盖
    agent_name: str = "base"
    max_reasoning_steps: int = 10

    def __init__(
        self,
        shared_memory: SharedWorkingMemory | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
    ):
        self.shared_memory = shared_memory
        # 优先使用外部传入的持久化 checkpointer（如 SqliteSaver），
        # 未传入时回退到内存 MemorySaver（开发/测试兼容）。
        self._memory_saver: BaseCheckpointSaver = checkpointer or MemorySaver()
        self._agent: CompiledStateGraph | None = None

    @property
    def memory_saver(self) -> BaseCheckpointSaver:
        return self._memory_saver

    @property
    def agent(self) -> CompiledStateGraph:
        """懒初始化 ReAct Agent。"""
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

    def _get_tools(self) -> list:
        """子类覆盖：返回工具列表。"""
        return []

    def _get_system_prompt(self) -> str:
        """子类覆盖：返回系统提示词。"""
        return "你是一个金融客服系统的专业 Agent。"

    def build_business_state(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        """构建业务执行所需的内部 JSON 状态；无要求的 Agent 默认可执行。"""
        return {
            "agent": self.agent_name,
            "status": "ready",
            "required_fields": {},
            "missing_fields": [],
        }

    def build_missing_fields_response(self, business_state: Dict[str, Any]) -> str:
        """根据业务状态一次性生成全部缺失字段的引导语。"""
        required = business_state.get("required_fields", {}) or {}
        missing = business_state.get("missing_fields", []) or []
        prompts = [
            str(required.get(field, {}).get("prompt", "")).strip()
            for field in missing
        ]
        prompts = [prompt for prompt in prompts if prompt]
        if not prompts:
            return "继续执行前，请补充必要的业务信息。"
        return "继续执行前，请补充以下信息：\n" + "\n".join(
            f"- {prompt}" for prompt in prompts
        )

    def _build_effective_message(
        self,
        message: str,
        customer_id: str = "",
        memory_context: str = "",
    ) -> str:
        """构建发送给 Agent 的有效消息，自动注入共享工作内存中的发现。

        核心增强：Agent 在执行时能看到其他 Agent 已确认的事实（通过 SharedWorkingMemory）。
        产品咨询 Agent 无需自己查询账户——共享内存中已有其他 Agent 放入的持仓/余额数据。
        """
        parts = []

        # 1. 注入共享工作内存中的事实（如持仓、余额等）
        if self.shared_memory and self.shared_memory.facts:
            facts_text = self.shared_memory.format_facts_for_prompt()
            if facts_text:
                parts.append(f"""[共享上下文]
以下是当前任务的内部分析材料，请直接回答用户问题，不要向用户说明材料来源：

{facts_text}""")

        # 2. 客户号
        if customer_id:
            parts.append(f"当前客户号：{customer_id}")

        # 3. 三层记忆上下文
        if memory_context:
            parts.append(memory_context)

        # 4. 当前用户输入
        parts.append(f"用户问题：{message}")

        return "\n\n".join(parts)

    def handle(
        self,
        message: str,
        customer_id: str = "",
        chat_history: List[Dict[str, str]] | None = None,
        thread_id: str | None = None,
        memory_context: str = "",
    ) -> str:
        """处理用户消息，返回回复字符串。

        Args:
            message: 当前用户输入
            customer_id: 已验证的客户号
            chat_history: 原始对话历史（可选，用于构建消息列表）
            thread_id: MemorySaver 的 thread_id，用于跨轮对话持久化

        Returns:
            Agent 生成的回复文本
        """
        effective = self._build_effective_message(
            message, customer_id, memory_context,
        )

        # 构建消息列表
        messages = []
        if chat_history:
            for item in chat_history[-8:]:
                role = item.get("role", "user")
                if role in {"user", "assistant"}:
                    messages.append({"role": role, "content": item.get("content", "")})
        messages.append({"role": "user", "content": effective})

        # 使用 ReAct Agent 执行（带 checkpoint 支持）
        config = {}
        if thread_id:
            config["configurable"] = {"thread_id": thread_id}

        try:
            result = self.agent.invoke({"messages": messages}, config=config)
        except Exception:
            # 如果 ReAct Agent 执行失败（如无限循环），回退到简单调用
            result = self.agent.invoke({"messages": messages})

        response = result["messages"][-1].content if result.get("messages") else "暂时无法生成回复。"

        # 检查并发布发现到共享工作内存
        self._maybe_publish_findings(message, response)

        return response

    async def handle_stream(
        self,
        message: str,
        customer_id: str = "",
        chat_history: List[Dict[str, str]] | None = None,
        thread_id: str | None = None,
        memory_context: str = "",
    ) -> AsyncIterator[Dict[str, Any]]:
        """流式处理消息，逐 token 或逐事件返回。

        支持流式输出，前端可以逐字展示。
        """
        effective = self._build_effective_message(
            message, customer_id, memory_context,
        )

        messages = []
        if chat_history:
            for item in chat_history[-8:]:
                role = item.get("role", "user")
                if role in {"user", "assistant"}:
                    messages.append({"role": role, "content": item.get("content", "")})
        messages.append({"role": "user", "content": effective})

        config = {}
        if thread_id:
            config["configurable"] = {"thread_id": thread_id}

        async for event in self.agent.astream_events(
            {"messages": messages},
            config=config,
            version="v2",
        ):
            kind = event.get("event", "")
            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    yield {
                        "type": "token",
                        "content": chunk.content,
                        "agent": self.agent_name,
                    }
            elif kind == "on_tool_start":
                yield {
                    "type": "tool_start",
                    "tool": event.get("name", ""),
                    "agent": self.agent_name,
                }
            elif kind == "on_tool_end":
                yield {
                    "type": "tool_end",
                    "tool": event.get("name", ""),
                    "agent": self.agent_name,
                }

    def _maybe_publish_findings(self, user_message: str, response: str) -> None:
        """分析 Agent 的回复，将结构化发现发布到共享工作内存。

        这样下游 Agent 可以直接利用已确认的信息，无需重复查询。
        """
        if not self.shared_memory:
            return

        import re

        # 提取 A股代码（6位数字：60xxxx/00xxxx/30xxxx/68xxxx）
        codes = re.findall(
            r"(?<!\d)(60\d{4}|00\d{4}|30\d{4}|68\d{4}|8\d{5}|4\d{5})(?!\d)", response
        )
        for code in set(codes):
            self.shared_memory.publish_fact(f"mentioned_stock_{code}", {
                "code": code,
                "mentioned_by": self.agent_name,
            })

        # 提取配置权重（如 30%、0.3）
        weights = re.findall(r"(\d+(?:\.\d+)?)\s*%", response)
        for weight in weights:
            try:
                value = float(weight) / 100
                if 0 < value <= 1:
                    self.shared_memory.publish_fact(
                        f"mentioned_weight_{self.agent_name}",
                        {"value": value, "source": self.agent_name},
                    )
            except ValueError:
                pass

        # 提取金额信息
        amounts = re.findall(r"(\d[\d,]*\.?\d*)\s*(元|万|千)", response)
        for amount, unit in amounts:
            try:
                value = float(amount.replace(",", ""))
                self.shared_memory.publish_fact(f"mentioned_amount_{self.agent_name}", {
                    "value": value,
                    "unit": unit,
                    "source": self.agent_name,
                })
            except ValueError:
                pass
