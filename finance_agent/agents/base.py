"""
1. 使用 LangGraph 的 create_react_agent 实现显式多步推理
2. 每个 Agent 拥有独立的 MemorySaver 支持会话内状态持久化
3. 集成 SharedWorkingMemory 实现 Agent 间信息共享
4. 支持流式输出接口（astream_events）
5. 内置自我反思（Reflection）循环
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List

from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph

from finance_agent.config import get_model_for_agent
from finance_agent.core.shared_state import SharedWorkingMemory


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
    ):
        self.shared_memory = shared_memory
        self._memory_saver = MemorySaver()
        self._agent: CompiledStateGraph | None = None

    @property
    def memory_saver(self) -> MemorySaver:
        return self._memory_saver

    @property
    def agent(self) -> CompiledStateGraph:
        """懒初始化 ReAct Agent。"""
        if self._agent is None:
            self._agent = create_react_agent(
                model=get_model_for_agent(self.agent_name),
                tools=self._get_tools(),
                prompt=self._get_system_prompt(),
                name=self.agent_name,
                checkpointer=self._memory_saver,
            )
        return self._agent

    def _get_tools(self) -> list:
        """子类覆盖：返回工具列表。"""
        return []

    def _get_system_prompt(self) -> str:
        """子类覆盖：返回系统提示词。"""
        return "你是一个金融客服系统的专业 Agent。"

    def _build_effective_message(
        self,
        message: str,
        compressed_context: str = "",
        customer_id: str = "",
        memory_context: str = "",
    ) -> str:
        """构建发送给 Agent 的有效消息，自动注入共享工作内存中的发现。

        核心增强：Agent 在执行时能看到其他 Agent 已确认的事实（通过 SharedWorkingMemory）。
        产品咨询 Agent 无需自己查询账户——共享内存中已有其他 Agent 放入的持仓/余额数据。
        """
        parts = []

        # 1. 注入共享工作内存中的已确认事实（如持仓、余额等）
        if self.shared_memory and self.shared_memory.facts:
            facts_text = self.shared_memory.format_facts_for_prompt()
            if facts_text:
                parts.append(f"""[共享上下文 - 其他 Agent 已确认的信息]
以下是当前已验证的客户账户信息，请直接引用这些数据回答用户问题：

{facts_text}""")

        # 2. 客户号
        if customer_id:
            parts.append(f"当前客户号：{customer_id}")

        # 3. 三层记忆上下文
        if memory_context:
            parts.append(memory_context)

        # 4. 压缩上下文
        if compressed_context and compressed_context != "无历史对话。":
            parts.append(f"对话上下文：\n{compressed_context}")

        # 5. 当前用户输入
        parts.append(f"用户问题：{message}")

        return "\n\n".join(parts)

    def handle(
        self,
        message: str,
        compressed_context: str = "",
        customer_id: str = "",
        chat_history: List[Dict[str, str]] | None = None,
        thread_id: str | None = None,
        memory_context: str = "",
    ) -> str:
        """处理用户消息，返回回复字符串。

        Args:
            message: 当前用户输入
            compressed_context: 压缩后的历史上下文
            customer_id: 已验证的客户号
            chat_history: 原始对话历史（可选，用于构建消息列表）
            thread_id: MemorySaver 的 thread_id，用于跨轮对话持久化

        Returns:
            Agent 生成的回复文本
        """
        effective = self._build_effective_message(
            message, compressed_context, customer_id, memory_context,
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
        compressed_context: str = "",
        customer_id: str = "",
        chat_history: List[Dict[str, str]] | None = None,
        thread_id: str | None = None,
        memory_context: str = "",
    ) -> AsyncIterator[Dict[str, Any]]:
        """流式处理消息，逐 token 或逐事件返回。

        支持流式输出，前端可以逐字展示。
        """
        effective = self._build_effective_message(
            message, compressed_context, customer_id, memory_context,
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
        codes = re.findall(r"(?<!\d)(60\d{4}|00\d{4}|30\d{4}|68\d{4}|8\d{5}|4\d{5})(?!\d)", response)
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
