"""确定性分析请求解析器测试。"""

from finance_agent.research.request_parser import parse_analysis_request


def test_slots_win_over_message_regex_for_comparison_and_indicators():
    """已提取的槽位优先于消息正则，且指标保持用户指定范围。"""
    request = parse_analysis_request(
        "比较茅台和招行的MACD",
        resolved_stocks=[{"code": "600519"}, {"code": "600036"}],
        intent_slots={"market_query": {"indicators": ["MACD"]}},
        user_profile={},
    )

    assert request.kind.value == "comparison"
    assert request.stock_codes == ["600519", "600036"]
    assert request.indicators == ["MACD"]


def test_profile_is_complete_only_with_risk_and_holding_period():
    """个性化分析只接受同时具备风险偏好和持有期限的画像。"""
    request = parse_analysis_request(
        "分析600519",
        resolved_stocks=[],
        intent_slots={},
        user_profile={"risk_preference": "R3", "holding_period": ""},
    )

    assert request.profile_complete is False
