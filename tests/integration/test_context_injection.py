"""上下文注入链路：滑动窗口 → 分类器/改写器 → 专家任务描述。

回归的是截图里的失效链：历史被拼成没有角色标签的一团文本、分类器提示词又不许用
上下文补全当前消息，指代性追问只能退化成一句与上下文无关的固定澄清；而唯一负责
把历史变成"自包含任务描述"的改写器又因缺 import 静默失效，历史根本到不了专家。
"""

from __future__ import annotations

import json

from finance_agent.application.turn_coordinator import DEFAULT_HISTORY_CHARS, _history_text
from tests.conftest import make_fake_supervisor_model
from finance_agent.orchestration.contracts import DomainOutcome
from finance_agent.orchestration.graphs.supervisor import (
    SupervisorDependencies,
    build_supervisor_graph,
)
from finance_agent.orchestration.memory import UserProfileCard
from finance_agent.orchestration.routing.task_rewrite import build_llm_rewriter

WINDOW = [
    {"role": "user", "content": "帮我看看110011和000001"},
    {"role": "assistant", "content": "两只基金的风险等级都是 R4 中高风险。"},
]


class _Memory:
    """最小记忆替身：只提供 TurnCoordinator 会读到的字段。"""

    window_size = 6
    max_context_chars = 6000

    def __init__(self, window):
        self._window = list(window)

    def load_context(self, customer_id, conversation_id, fallback_messages=None):
        return {
            "profile": {},
            "context_text": "",
            "sliding_window": list(self._window),
            "sliding_window_text": "",
        }

    def get_profile(self, customer_id):
        return UserProfileCard(customer_id=customer_id)


def _system(graph, memory, captured: dict):
    """按既有测试惯例用 ``object.__new__`` 构造宿主，只补必需的运行时字段。"""
    from finance_agent.application.advisor import AdvisorSystem

    system = object.__new__(AdvisorSystem)
    system._ensure_runtime_state()
    system.memory = memory
    system.supervisor = graph
    system.audit = type("A", (), {"create_run": lambda *a, **k: None})()
    system.get_checkpoint_conversation_messages = lambda *a, **k: []
    system._persist_param_profile = lambda *a, **k: None
    system._persist_pending_outcomes = lambda *a, **k: None
    system._persist = lambda *args, **kwargs: captured.__setitem__(
        "persist", {"args": args, "kwargs": kwargs},
    )
    return system


def _patch_rewrite_model(monkeypatch, model_output: str, prompts: list):
    """注入假改写模型（``build_llm_rewriter`` 在函数内导入工厂，故补丁打在工厂上）。"""
    from finance_agent.infrastructure.llm import factory

    def fake_call(messages):
        prompts.append(messages)
        return model_output

    monkeypatch.setattr(
        factory, "build_chat_model_callable", lambda model, require_json=True: fake_call,
    )


def test_history_is_role_labeled_and_truncated_to_the_tail():
    text = _history_text(WINDOW, limit=1000)

    assert text.startswith("用户: 帮我看看110011和000001")
    assert "助手: 两只基金的风险等级都是 R4 中高风险。" in text
    # 超长时保留最新内容（尾部），而不是把刚刚发生的对话截掉
    long_text = _history_text(WINDOW + [{"role": "user", "content": "最" * 200}], limit=80)
    assert long_text == "最" * 80
    assert "帮我看看110011和000001" not in long_text
    assert DEFAULT_HISTORY_CHARS >= 2000


def test_history_text_ignores_blank_messages():
    text = _history_text([
        {"role": "user", "content": "   "},
        {"role": "user", "content": "有效内容"},
    ])

    assert text == "用户: 有效内容"


def test_follow_up_carries_history_into_classifier_rewriter_and_expert(monkeypatch):
    """进程内端到端：同一份带角色的历史到达分类器与改写器，改写出的自包含
    描述再作为专家任务下发。"""
    prompts: list = []
    _patch_rewrite_model(
        monkeypatch,
        json.dumps(
            {"tasks": {"product_research": "基于 110011 与 000001 给出稳健型配置建议"}},
            ensure_ascii=False,
        ),
        prompts,
    )
    seen: dict = {}

    class _Classifier:
        def classify_intents(self, message, context_summary=""):
            seen["context_summary"] = context_summary
            return {
                "intents": [{
                    "intent": "product_analysis", "query": message, "confidence": 0.99,
                }],
                "uncertain_intents": [],
                "finance_related": True,
                "classification_error": {},
                "profile_facts": [{
                    "field": "risk_preference", "value": "R2 中低风险", "quote": "我是稳健型选手",
                }],
            }

    def domain_runner(context):
        seen["goal"] = context.task.goal
        return DomainOutcome(
            task_id=context.task.task_id,
            domain=context.task.domain,
            status="success",
            summary="配置建议已给出。",
        )

    graph = build_supervisor_graph(
        SupervisorDependencies(
            supervisor_model=make_fake_supervisor_model(),
            classifier=_Classifier(),
            domain_runner=domain_runner,
            rewriter=build_llm_rewriter(object()),
        )
    )
    captured: dict = {}
    system = _system(graph, _Memory(WINDOW), captured)

    output = system.handle_message(
        "我是稳健型选手，你有什么建议？", conversation_id="conv-1",
    )

    # 1) 分类器与改写器看到的是同一份带角色标签的历史
    assert "用户: 帮我看看110011和000001" in seen["context_summary"]
    assert "助手: 两只基金的风险等级都是 R4 中高风险。" in seen["context_summary"]
    assert "帮我看看110011和000001" in prompts[0][0]["content"]
    # 2) 改写出的自包含描述（而不是追问原话）到达专家
    assert seen["goal"] == "基于 110011 与 000001 给出稳健型配置建议"
    # 3) 模型自述候选随路由决策带出并交给持久化（落库前还有内存层的确定性门控）
    assert output["response"]
    assert captured["persist"]["kwargs"]["model_facts"] == [{
        "field": "risk_preference", "value": "R2 中低风险", "quote": "我是稳健型选手",
    }]


def test_persistence_forwards_model_facts_to_memory():
    """落库链路：轮末持久化必须把模型自述候选交给内存层的确定性门控。"""
    from finance_agent.application.run_persistence import PersistenceCoordinator

    facts = [{"field": "risk_preference", "value": "R2 中低风险", "quote": "我是稳健型选手"}]
    seen: dict = {}

    class _Memory:
        def append_window_message(self, *args, **kwargs):
            return True

        def update_profile_from_result(self, *args, **kwargs):
            seen["args"] = args
            seen["kwargs"] = kwargs
            return True

    class _DB:
        def append_conversation_message(self, *args, **kwargs):
            return None

        def rename_conversation_from_message(self, *args, **kwargs):
            return None

    host = type("H", (), {
        "memory": _Memory(),
        "audit": type("A", (), {"complete_run": lambda *a, **k: None})(),
        "_best_effort": lambda self, category, action: action(),
        "_bump_degradation": lambda self, category: None,
        "_audit_research_results": lambda self, state: None,
    })()
    coordinator = PersistenceCoordinator(host, _DB)

    coordinator.persist(
        "CUST001", "conv-1", "我是稳健型选手", {"response": "好的"}, "run-1",
        model_facts=facts,
    )

    assert seen["args"] == ("CUST001", "我是稳健型选手", {"response": "好的"})
    assert seen["kwargs"]["model_facts"] == facts
