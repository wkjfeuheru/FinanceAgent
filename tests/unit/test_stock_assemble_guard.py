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


# ── 代码落地守卫：拆掉"主题筛选前置拒绝"后，凭空列代码是新的风险面 ─────────────

def test_invented_stock_code_is_flagged():
    sink = _sink(stock_data={"600519": {"price": 1700}})

    assembly = stock_assemble(sink, "可以先关注 300308，另外 002230 也值得跟踪。")

    assert "analysis_code_not_grounded:300308" in assembly.limitations
    assert "analysis_code_not_grounded:002230" in assembly.limitations
    assert assembly.structured_data["analysis_grounding"]["ungrounded_codes"] == ["300308", "002230"]
    # 只披露不改写：用户可见正文原样保留。
    assert assembly.summary == "可以先关注 300308，另外 002230 也值得跟踪。"


def test_codes_from_tool_payload_are_grounded():
    """工具产物里出现过的代码（含嵌套键：``stock_analysis`` 的 {代码: ...}）不报警。"""
    sink = _sink(
        stock_analysis={"600519": {"rating": "关注"}},
        analysis_results=[{"action": "关注", "rule_version": "research_rules/v1"}],
    )

    assembly = stock_assemble(sink, "600519 综合评分 8.5 分，建议关注。")

    assert not any(code.startswith("analysis_code_not_grounded") for code in assembly.limitations)
    # 数字越界是另一条守卫（本轮没喂 8.5 的来源），这里只要求没有"代码"越界记录。
    assert "ungrounded_codes" not in (assembly.structured_data.get("analysis_grounding") or {})


def test_uuid_like_digits_are_not_treated_as_stock_codes():
    """8 位日期/序号不能被当成 6 位代码（前后有数字边界）。"""
    sink = _sink(stock_data={"600519": {"price": 1700}})

    assembly = stock_assemble(sink, "报告期 20260630，标的 600519 的趋势向上。")

    assert not any(code.startswith("analysis_code_not_grounded") for code in assembly.limitations)
