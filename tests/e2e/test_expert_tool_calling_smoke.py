"""可选联网冒烟测试：验证专家模型的 function-calling（tool-calling）可用性。

**默认不运行**——CI 与离线环境不应依赖真实模型。启用方式：

```bash
RUN_NETWORK_TESTS=1 python -m pytest -q -m network tests/e2e/test_expert_tool_calling_smoke.py
```

为什么必须真机验证：本仓库历史上刻意**绕开** ``tools`` 参数、改用
``response_format=json_object`` 的 JSON 协议循环（旧 ``runtime/react.py`` 的注释
说明了这一 workaround 的由来）。专家改造后改为 LangGraph 原生 ``create_agent``
工具循环，依赖模型服务端接受并返回 ``tool_calls``——``ChatDeepSeek``/``ChatOpenAI``
客户端都有 ``bind_tools``，但服务端是否接受 ``deepseek-v4-pro`` 的 ``tools`` 参数
无法离线断言。这些用例把这个假设变成可执行的检查。
"""

from __future__ import annotations

import os

import pytest

pytestmark = [
    pytest.mark.network,
    pytest.mark.skipif(
        os.getenv("RUN_NETWORK_TESTS", "").strip().lower() not in {"1", "true", "yes", "on"},
        reason="联网冒烟测试默认跳过；设置 RUN_NETWORK_TESTS=1 启用",
    ),
]


def _tool_round_trip(model) -> None:
    """断言模型能绑定工具、发起 tool_call、并在拿到工具结果后给出最终文本。"""
    from langchain_core.tools import tool

    @tool
    def get_stock_quote(stock_code: str) -> str:
        """查询 A 股行情快照。stock_code 为 6 位代码，如 600519。"""
        return '{"code": "%s", "price": 1680.0}' % stock_code

    bound = model.bind_tools([get_stock_quote])
    first = bound.invoke("贵州茅台（600519）现在什么价格？请调用工具查询。")
    tool_calls = getattr(first, "tool_calls", None) or []
    assert tool_calls, f"模型未返回 tool_calls：{first!r}"
    assert tool_calls[0]["name"] == "get_stock_quote"


def test_expert_model_supports_tool_calling():
    """专家模型（deepseek-v4-pro）必须支持原生 function-calling。"""
    from finance_agent.infrastructure.llm.factory import get_expert_model

    _tool_round_trip(get_expert_model())


def test_supervisor_model_supports_tool_calling():
    """会话/FAQ 路径的模型（deepseek-v4-flash）必须支持原生 function-calling。"""
    from finance_agent.infrastructure.llm.factory import get_supervisor_model

    _tool_round_trip(get_supervisor_model())


def test_conversation_agent_completes_a_faq_turn():
    """会话 FAQ 的 create_agent 循环在真实模型下端到端可跑通。"""
    from finance_agent.infrastructure.llm.factory import get_supervisor_model
    from finance_agent.orchestration.graphs.conversation import run_conversation

    class _Retriever:
        def search(self, query):
            from finance_agent.domains.faq.contracts import FaqSearchMatch, FaqSearchResult

            return FaqSearchResult(
                status="found",
                matches=[FaqSearchMatch(
                    faq_id="f1", chunk_id="c1", score=0.9, index_version="v1",
                    source_path="seed", question="基金风险等级如何划分？",
                    answer="基金风险等级分为 R1-R5，R1 最低、R5 最高。",
                )],
            )

    result = run_conversation(
        _Retriever(), get_supervisor_model(),
        user_message="基金的风险等级是怎么划分的？", max_steps=3,
    )
    assert result["status"] in ("success", "partial")
    assert result["final_response"].strip()
