"""名称分级匹配：全称/简称（后缀省略）/近似（错别字）与歧义澄清。"""

from __future__ import annotations

from finance_agent.shared import name_matching as name_match
from finance_agent.shared.name_matching import (
    match_names,
    normalise,
    prepare_query,
    strip_type_suffix,
    unclear_text,
)

_STOCKS = [
    {"code": "600519", "name": "贵州茅台"},
    {"code": "000858", "name": "五粮液"},
    {"code": "600036", "name": "招商银行"},
    {"code": "600999", "name": "招商证券"},
    {"code": "000001", "name": "平安银行"},
]


def _codes(message, items=_STOCKS):
    return match_names(message, items).codes


def test_full_name_exact_match_is_highest_tier():
    result = match_names("分析贵州茅台的基本面", _STOCKS)

    assert result.codes == ["600519"]
    assert result.candidates[0].tier == 3
    assert result.ambiguous is False


def test_abbreviated_name_substring_resolves_unique_stock():
    """简称（全称的子串）必须解析出唯一代码——旧逻辑会因全称未逐字出现而丢弃。"""
    result = match_names("帮我看看茅台走势", _STOCKS)

    assert result.codes == ["600519"]
    assert result.candidates[0].tier == 2


def test_requirement_noise_is_stripped_before_matching():
    assert normalise(" 贵州 茅台 ") == "贵州茅台"
    assert prepare_query("帮我分析一下贵州茅台怎么样").tokens == ("贵州茅台",)


def test_typo_is_matched_by_similarity():
    """错一字（同长度、公共块 ≥2）应命中，而不是报"未识别"。"""
    result = match_names("分析贵州毛台", _STOCKS)

    assert result.codes == ["600519"]
    assert result.candidates[0].tier == 1


def test_ambiguous_abbreviation_is_flagged_not_guessed():
    """缩写命中多个标的时不得静默选择，必须记为歧义并给出候选。"""
    result = match_names("招商怎么样", _STOCKS)

    assert result.codes == []
    assert result.ambiguous_tokens == ["招商"]
    assert {candidate.code for candidate in result.candidates} == {"600036", "600999"}


def test_multiple_names_in_one_message_all_resolve():
    """同一句里既有全称又有简称时，两者都要解析（不得因全称命中就短路）。"""
    assert sorted(_codes("比较贵州茅台和五粮液")) == ["000858", "600519"]
    assert sorted(_codes("比较茅台和五粮液")) == ["000858", "600519"]


def test_generic_industry_token_does_not_abbreviate():
    """"银行"这类通用词单独出现时不足以指代标的，不得匹配成唯一结果。"""
    result = match_names("银行", _STOCKS)

    assert result.codes == []
    assert result.candidates == []


def test_unrelated_query_matches_nothing():
    assert _codes("今天大盘怎么样") == []
    assert _codes("这个基金可以买吗") == []


def test_empty_items_or_message_yield_empty_result():
    assert match_names("分析茅台", []).codes == []
    assert match_names("", _STOCKS).codes == []


def test_max_codes_limits_results():
    items = [{"code": f"60{i:04d}", "name": f"甲公司第{i}号"} for i in range(5)]
    result = match_names("甲公司第0号 甲公司第1号 甲公司第2号 甲公司第3号", items, max_codes=3)

    assert len(result.codes) == 3


def test_strip_type_suffix_aligns_short_and_full_product_names():
    suffixes = ("基金", "ETF", "混合", "指数")
    assert strip_type_suffix("易方达中小盘混合", suffixes) == "易方达中小盘"
    assert strip_type_suffix("华夏成长基金", suffixes) == "华夏成长"
    # 纯类型词不得被削成空串（调用方应据此判定为"无名称"）。
    assert strip_type_suffix("基金", suffixes) == "基金"


def test_unclear_text_lists_candidate_names_and_codes():
    result = match_names("招商怎么样", _STOCKS)
    text = unclear_text("招商", result.candidates)

    assert "招商银行" in text and "600036" in text
    assert "招商证券" in text and "600999" in text
    assert "6 位代码" in text


def test_public_helpers_exported():
    for name in ("match_names", "normalise", "prepare_query", "strip_type_suffix",
                 "unclear_text", "tier_of", "Candidate", "NameMatch"):
        assert hasattr(name_match, name)
