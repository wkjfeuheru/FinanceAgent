"""研究结果的确定性报告渲染器。"""

from __future__ import annotations

from finance_agent.research.contracts import AnalysisResult


class NarrativeRenderer:
    """当前阶段使用固定模板，保留后续接入受限 LLM 的边界。"""

    def render(self, result: AnalysisResult) -> tuple[str, str]:
        """返回文本和报告模式，绝不修改结构化结论。"""
        action = result.action.value
        restrictions = "；".join(result.scores.keys()) if result.scores else "无"
        candidate_notice = (
            "当前为非个性化研究候选。"
            if result.personalization_status == "research_candidate"
            else "已结合必填用户画像。"
        )
        return (
            f"确定性研究结论：{action}。规则版本：{result.rule_version or '未设置'}。"
            f"数据质量：{result.data_quality}。{candidate_notice}评分项：{restrictions}。",
            "template_fallback",
        )
