"""Agent 基类与协议。

当前架构由总管在 LangGraph 状态图内统一编排，各专家实现 ``invoke(state)``
并按需直接调用模型或确定性流水线；不依赖 create_react_agent 的多步推理循环。
"""

from __future__ import annotations

from typing import Any, Dict


class AgentProtocol:
    """Agent 抽象协议 —— 所有 Agent 必须实现 invoke(state)。"""

    agent_name: str = "base"

    def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError(
            f"{self.__class__.__name__} 必须实现 invoke(state) 方法"
        )


class ProceduralAgent(AgentProtocol):
    """过程式 Agent —— 无 LLM 循环，用于数据获取/预处理与确定性分析。"""

    agent_name: str = "procedural"

    def __init__(self, **_: Any):
        pass

    def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        return state
