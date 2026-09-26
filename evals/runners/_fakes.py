"""评测专用假模型：让评测驱动根图时无需真实 LLM。

评测（``evals/runners/*``）会调用 ``build_supervisor_graph`` 跑真实代码路径。根图的
``supervisor`` 节点需要 LLM 决策，因此这里提供一个确定性替代：对**全部已绑定域**
发起并行 handoff（等价于"选中候选全集"），候选集外的调用会被 handoff 工具拒绝并
丢弃，最终结果恰好等于分类器给出的候选领域集合。

与 ``tests/conftest.py`` 的同名工厂保持等价语义，但评测包**不依赖** ``tests``。
"""

from __future__ import annotations

from typing import Any, Iterable

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult


def deterministic_supervisor_model(select: Iterable[str] | None = None) -> Any:
    """构造确定性的 supervisor 决策假模型。

    ``select`` 为 None 时选择全部已绑定域；否则只选择给定领域（``BusinessDomain.value``
    或 ``transfer_to_<domain>`` 工具名）。
    """
    wanted_override = list(select) if select is not None else None

    class _DeterministicSupervisorModel(GenericFakeChatModel):  # type: ignore[misc, valid-type]
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(messages=iter([]), **kwargs)
            object.__setattr__(self, "_bound", [])
            object.__setattr__(self, "_turn", 0)

        def bind_tools(self, tools: list[Any], **kwargs: Any) -> Any:
            object.__setattr__(
                self,
                "_bound",
                [str(getattr(entry, "name", "")) for entry in tools if getattr(entry, "name", None)],
            )
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
            turn = getattr(self, "_turn", 0)
            object.__setattr__(self, "_turn", turn + 1)
            if turn > 0:
                return ChatResult(
                    generations=[ChatGeneration(message=AIMessage(content="路由完成。"))]
                )
            bound = list(getattr(self, "_bound", []))
            if wanted_override is None:
                wanted = bound
            else:
                wanted = [
                    item if item.startswith("transfer_to_") else f"transfer_to_{item}"
                    for item in wanted_override
                ]
            tool_calls = [
                {
                    "name": name,
                    "args": {"task_description": "按用户请求处理该领域任务。"},
                    "id": f"sup-{index}",
                    "type": "tool_call",
                }
                for index, name in enumerate(wanted)
                if name in bound
            ]
            return ChatResult(
                generations=[ChatGeneration(message=AIMessage(content="", tool_calls=tool_calls))]
            )

    return _DeterministicSupervisorModel()
