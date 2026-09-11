"""研究结果的确定性报告渲染器。"""

from __future__ import annotations

from finance_agent.research.contracts import AnalysisResult


# 限制原因码 → 面向用户的中文说明。原因码本身保持稳定，供审计与前端复用。
_RESTRICTION_TEXT: dict[str, str] = {
    "price_history": "缺少足够的历史收盘价",
    "fundamental_metrics": "缺少可用的财务或估值指标",
    "risk_history": "缺少计算风险所需的行情",
    "stock_data": "未获取到该股票数据",
    "quote": "缺少最新报价",
    "adjusted_history": "缺少前复权历史行情",
    "quote_as_of_missing": "报价缺少数据日期",
    "stale_quote": "最新报价超过允许的数据新鲜度",
    "history_as_of_missing": "历史行情缺少数据日期",
    "stale_history": "最新 K 线超过允许的数据新鲜度",
    "mixed_report_period": "比较标的的财务报告期不一致",
    "fundamental_report_period_missing": "财务数据缺少报告期",
    "stale_fundamental_report_period": "财务报告期过于陈旧",
    "fundamental_disclosure_date_missing": "财务数据缺少披露日期",
    "fundamental_disclosure_before_period": "披露日期早于报告期",
    "fundamental_disclosure_in_future": "披露日期晚于评估时点",
    "valuation_not_ttm": "估值使用静态 PE 而非 TTM",
    "valuation_metrics_missing": "缺少可用估值指标（PE）",
    "mixed_sources": "不同数据项来自不同数据源",
    "trading_calendar_unavailable": "交易日历不可用，新鲜度按工作日估算",
}
# 评分字段名 → 报告用中文标签；不得把它们当作限制项展示。
_SCORE_LABELS: tuple[tuple[str, str], ...] = (
    ("fundamental", "基本面"),
    ("technical", "技术面"),
    ("risk", "风险"),
    ("suitability", "适配度"),
    ("total", "综合"),
)


def _restriction_items(restrictions: list[str]) -> list[str]:
    """把原因码翻译为中文说明；未知原因码原样保留，避免隐藏信息。"""
    items: list[str] = []
    for raw in restrictions or []:
        code = str(raw).strip()
        if not code:
            continue
        text = _RESTRICTION_TEXT.get(code, code)
        if text not in items:
            items.append(text)
    return items


def _score_items(scores: dict[str, float | None]) -> list[str]:
    """只列出可计算的评分项，缺失项不冒充 0 分。"""
    items: list[str] = []
    for key, label in _SCORE_LABELS:
        value = (scores or {}).get(key)
        if value is None:
            continue
        try:
            items.append(f"{label} {float(value):.1f}")
        except (TypeError, ValueError):
            continue
    return items


class NarrativeRenderer:
    """当前阶段使用固定模板，保留后续接入受限 LLM 的边界。"""

    def render(self, result: AnalysisResult) -> tuple[str, str]:
        """返回文本和报告模式，绝不修改结构化结论。"""
        action = result.action.value
        candidate_notice = (
            "当前为非个性化研究候选。"
            if result.personalization_status == "research_candidate"
            else "已结合必填用户画像。"
        )
        codes = result.request.stock_codes if result.request is not None else []
        # 比较请求会产出多条结论，文本必须标明各自标的，否则无法对应。
        target = f"（{codes[0]}）" if len(codes) == 1 else ""
        score_items = _score_items(result.scores)
        scores_text = "、".join(score_items) if score_items else "不可计算"
        limitations = _restriction_items(result.restrictions)
        limitations_text = "；".join(limitations) if limitations else "无"
        return (
            f"确定性研究结论{target}：{action}。规则版本：{result.rule_version or '未设置'}。"
            f"数据质量：{result.data_quality}。{candidate_notice}"
            f"评分：{scores_text}。"
            f"限制与提示：{limitations_text}。",
            "template_fallback",
        )
