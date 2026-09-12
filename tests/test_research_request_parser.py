"""确定性分析请求解析器测试。"""

import pytest

from finance_agent.research.request_parser import UnknownThemeError, parse_analysis_request


def test_slots_win_over_message_regex_for_comparison_and_indicators():
    """已提取的槽位优先于消息正则，且指标保持用户指定范围。"""
    request = parse_analysis_request(
        "比较茅台和招行的MACD",
        resolved_stocks=[{"code": "600519"}, {"code": "600036"}],
        intent_slots={"stock_analysis": {"indicators": ["MACD"]}},
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


def test_theme_request_without_stock_code_is_parsed_as_theme_screening():
    request = parse_analysis_request(
        "推荐人工智能主题股票",
        resolved_stocks=[],
        intent_slots={},
        user_profile={},
    )

    assert request.kind.value == "theme_screening"
    assert request.theme_id == "ai_compute"
    assert request.stock_codes == []


def test_explicit_theme_id_wins_without_stock_code():
    request = parse_analysis_request(
        "给我主题候选",
        resolved_stocks=[],
        intent_slots={"stock_recommendation": {"theme_id": "ai_compute"}},
        user_profile={},
    )

    assert request.kind.value == "theme_screening"
    assert request.theme_id == "ai_compute"


def test_unknown_theme_raises_typed_error_carrying_theme_text():
    """未注册主题抛可携带文本的类型化错误，供上层改用候选搜索。"""
    with pytest.raises(UnknownThemeError) as excinfo:
        parse_analysis_request(
            "推荐新能源主题股票",
            resolved_stocks=[],
            intent_slots={},
            user_profile={},
        )

    assert "主题" in str(excinfo.value)
    assert excinfo.value.theme_text


def test_unknown_theme_slot_is_ignored_when_codes_present():
    """有明确股票代码时，未注册的主题文本不应阻断个股分析。"""
    request = parse_analysis_request(
        "分析600519",
        resolved_stocks=[],
        intent_slots={"stock_analysis": {"themes": ["新能源"]}},
        user_profile={},
    )

    assert request.kind.value == "single_stock"
    assert request.theme_id is None
    assert request.stock_codes == ["600519"]


def test_slot_themes_key_resolves_registered_theme():
    """槽位 themes 键（自由文本）经注册表解析为主题筛选。"""
    request = parse_analysis_request(
        "给我推荐",
        resolved_stocks=[],
        intent_slots={"stock_recommendation": {"themes": ["人工智能"]}},
        user_profile={},
    )

    assert request.kind.value == "theme_screening"
    assert request.theme_id == "ai_compute"
