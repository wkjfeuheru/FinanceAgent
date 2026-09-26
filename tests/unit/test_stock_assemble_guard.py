"""股票专家 assemble 守卫：给结论必须经过确定性内核。

提示词里的硬约束（给个股结论/评级/评分前必须先调 ``evaluate_research``）不是强制
机制；本守卫把它变成确定性判定：写了结论性措辞但本轮没有 ``analysis_results``
（评估工具的唯一落点）时，登记 ``research_evaluation_missing`` 并把该域结论降为
``partial``——只披露与降级，不改写模型文案。
"""

from __future__ import annotations

from finance_agent.domains.research.expert.assemble import (
    EVALUATION_MISSING,
    stock_assemble,
)
from finance_agent.orchestration.contracts import BusinessDomain
from finance_agent.orchestration.experts.base import ExpertSink


def _sink(**structured) -> ExpertSink:
    sink = ExpertSink(domain=BusinessDomain.STOCK_RESEARCH)
    sink.structured.update(structured)
    return sink


def test_conclusion_without_evaluation_is_downgraded_and_flagged():
    sink = _sink(stock_data={"600519": {"price": 1700}})

    assembly = stock_assemble(sink, "综合评分 8.5 分，建议关注。")

    assert assembly.status == "partial"
    assert EVALUATION_MISSING in assembly.limitations
    assert assembly.structured_data["research_evaluation_missing"] is True
    # 文案原样保留：守卫只降级标注，不改写用户可见内容。
    assert assembly.summary == "综合评分 8.5 分，建议关注。"


def test_conclusion_with_evaluation_keeps_success():
    sink = _sink(analysis_results=[{"action": "关注", "rule_version": "research_rules/v1"}])

    assembly = stock_assemble(sink, "综合评分 8.5 分，建议关注。")

    assert assembly.status == "success"
    assert EVALUATION_MISSING not in assembly.limitations
    assert "research_evaluation_missing" not in assembly.structured_data


def test_plain_data_narrative_is_not_flagged():
    """只陈述取数结果、没有结论性措辞时不降级（避免误伤常规问答）。"""
    sink = _sink(stock_data={"600519": {"revenue": "1000 亿元"}})

    assembly = stock_assemble(sink, "2024 年营业收入 1000 亿元，同比增长 12%。")

    assert assembly.status == "success"
    assert EVALUATION_MISSING not in assembly.limitations


def test_needs_input_conclusion_is_left_untouched():
    from finance_agent.orchestration.needs_input import build_form

    sink = _sink()
    sink.pending_input = build_form([(BusinessDomain.STOCK_RESEARCH, ("stock_target",))])

    assembly = stock_assemble(sink, "请补充标的，我再给出评级。")

    assert assembly.status == "needs_input"
    assert EVALUATION_MISSING not in assembly.limitations
