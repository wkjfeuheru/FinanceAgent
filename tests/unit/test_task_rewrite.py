"""任务改写器：历史必须真的进入改写，模型输出必须真的被采用。

回归的是历史缺陷：``task_rewrite`` 用了 ``json`` 却没 import，每次调用都在
``json.loads`` 处抛 ``NameError``，被宽泛的 ``except Exception`` 吞掉——改写器静默
失效，指代性追问只能拿到未补全的原话（表现为"系统没看上下文"）。
"""

from __future__ import annotations

import json

from finance_agent.orchestration.contracts import BusinessDomain
from finance_agent.orchestration.routing import task_rewrite


def _rewriter_with(monkeypatch, model_output: str, captured: list | None = None):
    """注入假模型调用。

    ``build_llm_rewriter`` 在**函数内部**导入 ``build_chat_model_callable``，因此补丁
    必须打在工厂模块上（打在 ``task_rewrite`` 上不生效）。
    """
    from finance_agent.infrastructure.llm import factory

    def fake_call(messages):
        if captured is not None:
            captured.append(messages)
        return model_output

    monkeypatch.setattr(
        factory, "build_chat_model_callable", lambda model, require_json=True: fake_call,
    )
    return task_rewrite.build_llm_rewriter(object())


def test_rewriter_uses_model_output_instead_of_raw_message(monkeypatch):
    """改写器必须真的采用模型输出：退回原话就是"上下文没被用上"。"""
    rewriter = _rewriter_with(
        monkeypatch,
        json.dumps({"tasks": {"stock_research": "分析 110011 与 000001 的稳健配置"}},
                   ensure_ascii=False),
    )

    out = rewriter(
        {"user_message": "这两只怎么配", "run": {"routing": {}}},
        [BusinessDomain.STOCK_RESEARCH],
    )

    assert out["stock_research"] == "分析 110011 与 000001 的稳健配置"


def test_rewriter_falls_back_when_model_output_is_not_json(monkeypatch):
    rewriter = _rewriter_with(monkeypatch, "抱歉，我无法完成改写。")

    out = rewriter(
        {"user_message": "帮我看看这两只基金", "run": {"routing": {}}},
        [BusinessDomain.STOCK_RESEARCH],
    )

    assert out["stock_research"] == "帮我看看这两只基金"


def test_rewriter_falls_back_to_scoped_query_when_entities_are_dropped(monkeypatch):
    """改写丢了用户给的代码时必须回退：不能让专家收到丢掉标的的描述。"""
    rewriter = _rewriter_with(
        monkeypatch,
        json.dumps({"tasks": {"stock_research": "分析一下这只股票"}}, ensure_ascii=False),
    )

    out = rewriter(
        {
            "user_message": "分析600519",
            "run": {"routing": {"domain_queries": {"stock_research": "分析600519"}}},
        },
        [BusinessDomain.STOCK_RESEARCH],
    )

    assert out["stock_research"] == "分析600519"


def test_rewriter_prompt_carries_recent_context(monkeypatch):
    """提示词里必须带上近期上下文与当前消息，改写才有指代消解的依据。"""
    captured: list = []
    rewriter = _rewriter_with(
        monkeypatch,
        json.dumps({"tasks": {"stock_research": "分析 110011 的回撤"}}, ensure_ascii=False),
        captured,
    )

    rewriter(
        {
            "user_message": "那它回撤大吗",
            "history": "用户: 110011 怎么样\n助手: 110011 近期回撤较大",
            "run": {"routing": {}},
        },
        [BusinessDomain.STOCK_RESEARCH],
    )

    prompt = captured[0][0]["content"]
    assert "110011 近期回撤较大" in prompt
    assert "那它回撤大吗" in prompt
