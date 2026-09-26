"""股票专家的 ``assemble``：通用汇总 + "给结论必须经过确定性内核"守卫。

为什么需要这一层：股票域的 system prompt 硬约束第 3 条要求"给出个股结论、评级或
综合评分前必须先调用 ``evaluate_research``"，但**提示词不是强制机制**——模型完全可以
跳过它直接写"综合评分 8.5 分，建议关注"，而服务端只会事后登记数字越界（
``analysis_number_not_grounded``），结论本身照样下发。

本模块把那条硬约束变成确定性守卫：模型写了结论性措辞、而本轮 ``sink`` 里没有
``analysis_results``（``evaluate_research`` 的唯一写入路径）时，

- 登记 ``research_evaluation_missing`` 局限（进入 warnings 与结构化数据，可审计）；
- 该领域结论降为 ``partial``（由此整轮 run_status 也会是 partial，而不是"完全成功"）。

守卫**只披露与降级，不改写也不拦截**模型文案：把一次可用的分析整体丢掉，比如实标注
"这段结论没有确定性依据"更糟。措辞表刻意保守（只匹配结论性主张），避免把正常叙述
误判为结论。
"""

from __future__ import annotations

import re
from typing import Any

from finance_agent.orchestration.experts.base import (
    ExpertAssembly,
    ExpertSink,
    _json_text,
    default_assemble,
)

#: 结论性措辞：出现这些表达意味着模型在给"判断"而不只是陈述数据。
#: 保守清单——宁可漏判（少一次降级标注），不可误判（把数据叙述说成无依据结论）。
_CONCLUSION_RE = re.compile(
    r"评级|评分|得分|打分|建议关注|建议规避|予以.{0,4}评级|目标价|投资建议|"
    r"建议买入|建议卖出|建议增持|建议减持|综合推荐"
)

#: 6 位 A 股代码（与 ``AnalysisRequest`` 接受的代码段同口径）。
_STOCK_CODE_RE = re.compile(r"(?<!\d)(?:60\d{4}|00\d{4}|30\d{4}|68\d{4}|8\d{5}|4\d{5})(?!\d)")

#: 守卫触发时登记的局限码。
EVALUATION_MISSING = "research_evaluation_missing"


def stock_assemble(sink: ExpertSink, final_text: str) -> ExpertAssembly:
    """通用汇总 + 结论性措辞的确定性内核守卫 + 代码落地守卫。"""
    assembly = default_assemble(sink, final_text)
    # 缺参结论、以及已经调用过评估工具的情况都不适用。
    if assembly.status == "needs_input":
        return assembly

    # 代码落地检查先做：它不依赖结论性措辞——"凭空列一串代码"本身就是问题。
    assembly = _apply_code_grounding(assembly, final_text)
    if _has_evaluation(assembly.structured_data):
        return assembly
    if not final_text or not _CONCLUSION_RE.search(final_text):
        return assembly

    if EVALUATION_MISSING not in assembly.limitations:
        assembly.limitations.append(EVALUATION_MISSING)
    structured: dict[str, Any] = dict(assembly.structured_data)
    structured.setdefault("research_evaluation_missing", True)
    assembly.structured_data = structured
    if assembly.status == "success":
        assembly.status = "partial"
    return assembly


def _apply_code_grounding(assembly: ExpertAssembly, final_text: str) -> ExpertAssembly:
    """回答里出现工具产物之外的 6 位代码时，如实登记（只披露，不改写）。

    为什么要这条：主题/板块筛选以前由"模型调用前的固定拒绝"兜底，拆掉之后
    "模型凭空列一串股票代码候选"成为新的风险面。措辞与数字越界（
    ``analysis_number_not_grounded``）同一取舍——宁可标注"这个代码没有依据"，
    也不静默改写或整段丢弃。
    """
    ungrounded = _ungrounded_codes(final_text, assembly.structured_data)
    if not ungrounded:
        return assembly
    structured: dict[str, Any] = dict(assembly.structured_data)
    grounding = dict(structured.get("analysis_grounding") or {})
    grounding["ungrounded_codes"] = ungrounded
    structured["analysis_grounding"] = grounding
    assembly.structured_data = structured
    for code in ungrounded:
        limitation = f"analysis_code_not_grounded:{code}"
        if limitation not in assembly.limitations:
            assembly.limitations.append(limitation)
    return assembly


def _ungrounded_codes(analysis: str, structured: dict[str, Any] | None) -> list[str]:
    """找出回答里出现、但工具产物中不存在的代码（保序去重）。

    "存在"以工具结构化产物的 JSON 文本为准：代码既可能是顶层键（如
    ``stock_analysis`` 的 ``{代码: {...}}``），也可能嵌在证据快照里。
    """
    if not analysis:
        return []
    haystack = _json_text(structured or {})
    return [
        code
        for code in dict.fromkeys(_STOCK_CODE_RE.findall(str(analysis)))
        if code not in haystack
    ]


def _has_evaluation(structured: dict[str, Any] | None) -> bool:
    """本轮是否产出了确定性研究结论（``evaluate_research`` 的落点）。"""
    return bool((structured or {}).get("analysis_results"))


__all__ = ["EVALUATION_MISSING", "stock_assemble"]
