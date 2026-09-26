"""确定性分析请求解析器测试。"""

from finance_agent.domains.research.request_parser import parse_analysis_request


def test_slots_win_over_message_regex_for_comparison():
    request = parse_analysis_request(
        "比较茅台和招行",
        resolved_stocks=[{"code": "600519"}, {"code": "600036"}],
        intent_slots={"stock_analysis": {}},
        user_profile={},
    )
    assert request.kind.value == "comparison"
    assert request.stock_codes == ["600519", "600036"]


def test_analysis_type_slot_is_read_and_defaults_to_both():
    narrowed = parse_analysis_request(
        "只看技术面", resolved_stocks=[{"code": "600519"}],
        intent_slots={"stock_analysis": {"analysis_type": "technical"}}, user_profile={},
    )
    default = parse_analysis_request(
        "分析600519", resolved_stocks=[], intent_slots={}, user_profile={},
    )
    illegal = parse_analysis_request(
        "分析600519", resolved_stocks=[],
        intent_slots={"stock_analysis": {"analysis_type": "bogus"}}, user_profile={},
    )
    assert narrowed.analysis_type == "technical"
    assert default.analysis_type == "both"
    assert illegal.analysis_type == "both"


def test_profile_is_complete_only_with_risk_and_holding_period():
    request = parse_analysis_request(
        "分析600519", resolved_stocks=[], intent_slots={},
        user_profile={"risk_preference": "R3", "holding_period": ""},
    )
    assert request.profile_complete is False
