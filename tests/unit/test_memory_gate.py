"""长期画像候选与确认门控测试。"""

from finance_agent.orchestration.memory import (
    AgentMemoryContext,
    ProfileFactCandidate,
    UserProfileCard,
)


def build_memory_context(profile: UserProfileCard):
    context = object.__new__(AgentMemoryContext)
    context.get_profile = lambda customer_id: profile
    saved = []
    context.save_profile = lambda value: saved.append(value) or True
    return context, saved


def test_unconfirmed_inference_does_not_update_profile():
    profile = UserProfileCard(customer_id="CUST001")
    context, saved = build_memory_context(profile)

    candidates = context.extract_profile_candidates("看起来我应该适合稳健型配置")
    assert candidates
    assert all(not candidate.confirmed for candidate in candidates)
    assert context.apply_confirmed_facts("CUST001", candidates) is True
    assert saved == []
    assert profile.risk_preference == ""


def test_explicit_user_facts_are_persisted():
    profile = UserProfileCard(customer_id="CUST001")
    context, saved = build_memory_context(profile)

    candidates = context.extract_profile_candidates(
        "我的风险偏好是稳健，预算10万元，持有1年，投资目标是稳健增值，关注600519"
    )
    assert context.apply_confirmed_facts("CUST001", candidates) is True
    assert len(saved) == 1
    assert profile.risk_preference == "R2 中低风险"
    assert profile.budget_amount == 100000
    assert profile.holding_period == "1年"
    assert profile.investment_goal == "稳健增值"
    assert profile.stock_codes == ["600519"]
    assert profile.confirmed_facts["budget_amount"] == 100000


def test_amount_context_prevents_amount_being_saved_as_stock_code():
    """金额语境排除：'预算400000元'不得把 400000 当成北交所代码写入画像。"""
    profile = UserProfileCard(customer_id="CUST001")
    context, saved = build_memory_context(profile)

    candidates = context.extract_profile_candidates("我的预算是400000元")
    assert context.apply_confirmed_facts("CUST001", candidates) is True

    assert profile.budget_amount == 400000
    assert profile.stock_codes == []
    assert saved and saved[0].stock_codes == []


def test_real_stock_code_after_amount_context_is_still_extracted():
    """排除金额语境不得误伤真实代码：北交所代码仍正常提取。"""
    profile = UserProfileCard(customer_id="CUST001")
    context, saved = build_memory_context(profile)

    candidates = context.extract_profile_candidates("关注430047和600519")
    assert context.apply_confirmed_facts("CUST001", candidates) is True

    assert profile.stock_codes == ["430047", "600519"]


def test_recommendation_candidate_cannot_update_profile():
    profile = UserProfileCard(customer_id="CUST001")
    context, saved = build_memory_context(profile)

    recommendation = ProfileFactCandidate(
        field="stock_code", value="000001", source="expert_recommendation"
    )
    assert context.apply_confirmed_facts("CUST001", [recommendation]) is True
    assert saved == []
    assert profile.stock_codes == []


def test_legacy_update_ignores_expert_profile_result():
    profile = UserProfileCard(customer_id="CUST001")
    context, saved = build_memory_context(profile)

    assert context.update_profile_from_result(
        "CUST001",
        "请分析一只银行股",
        {"user_profile": {"investment_goal": "高收益"}, "explicit_user_stock_codes": ["000001"]},
    ) is True
    assert saved == []
    assert profile.investment_goal == ""
    assert profile.stock_codes == []


# ── 模型自述候选（模型自主判断 + 确定性门控）────────────────────────────────

def test_model_declared_risk_preference_is_persisted():
    """用户自述"我是稳健型选手"由模型判断为值得记住的事实，门控通过后写入。"""
    profile = UserProfileCard(customer_id="CUST001")
    context, saved = build_memory_context(profile)
    message = "我是稳健型选手，你有什么建议？"

    assert context.update_profile_from_result(
        "CUST001", message, None,
        [{"field": "risk_preference", "value": "R2 中低风险", "quote": "我是稳健型选手"}],
    ) is True

    assert len(saved) == 1
    assert profile.risk_preference == "R2 中低风险"
    assert profile.confirmed_facts["risk_preference"] == "R2 中低风险"


def test_model_fact_requires_verbatim_quote_from_this_turn():
    """quote 不在本轮用户原话里 → 丢弃：模型不得凭上下文或推测写长期记忆。"""
    profile = UserProfileCard(customer_id="CUST001")
    context, saved = build_memory_context(profile)

    assert context.apply_model_facts(
        "CUST001",
        [{"field": "risk_preference", "value": "R5 高风险", "quote": "我的风险偏好是高风险"}],
        "我是稳健型选手，你有什么建议？",
    ) is True

    assert saved == []
    assert profile.risk_preference == ""


def test_model_fact_value_must_match_quote_keywords():
    """值域/关键词必须一致：quote 说"激进"，就不能写成 R2。"""
    profile = UserProfileCard(customer_id="CUST001")
    context, saved = build_memory_context(profile)

    context.apply_model_facts(
        "CUST001",
        [{"field": "risk_preference", "value": "R2 中低风险", "quote": "我比较激进"}],
        "我比较激进",
    )

    assert saved == []
    assert profile.risk_preference == ""


def test_bare_risk_level_is_normalized_to_the_canonical_value():
    """"R2" 与 "R2 中低风险" 是同一档；但模型把"中高风险"写成 R5 必须被拒绝。"""
    profile = UserProfileCard(customer_id="CUST001")
    context, saved = build_memory_context(profile)

    context.apply_model_facts(
        "CUST001",
        [{"field": "risk_preference", "value": "R2", "quote": "我是稳健型选手"}],
        "我是稳健型选手",
    )
    assert len(saved) == 1
    assert profile.risk_preference == "R2 中低风险"

    context2, saved2 = build_memory_context(UserProfileCard(customer_id="CUST002"))
    context2.apply_model_facts(
        "CUST002",
        [{"field": "risk_preference", "value": "R5 高风险", "quote": "我能承受中高风险"}],
        "我能承受中高风险",
    )
    assert saved2 == []


def test_model_fact_without_risk_keyword_is_rejected():
    """没有关键词支持的猜测（"你觉得我适合什么"）不得成为长期事实。"""
    profile = UserProfileCard(customer_id="CUST001")
    context, saved = build_memory_context(profile)

    context.apply_model_facts(
        "CUST001",
        [{"field": "risk_preference", "value": "R5 高风险", "quote": "你觉得我适合什么"}],
        "你觉得我适合什么？",
    )

    assert saved == []
    assert profile.risk_preference == ""


def test_model_facts_cannot_write_stock_codes():
    """代码不走模型路径：金额与代码的混淆由正则抽取规则统一处理。"""
    profile = UserProfileCard(customer_id="CUST001")
    context, saved = build_memory_context(profile)

    context.apply_model_facts(
        "CUST001",
        [{"field": "stock_code", "value": "600519", "quote": "关注600519"}],
        "关注600519",
    )

    assert saved == []
    assert profile.stock_codes == []


def test_model_budget_and_horizon_must_match_numbers_in_quote():
    profile = UserProfileCard(customer_id="CUST001")
    context, saved = build_memory_context(profile)

    context.apply_model_facts(
        "CUST001",
        [
            {"field": "budget_amount", "value": "100000", "quote": "我的预算是10万"},
            {"field": "holding_period", "value": "1年", "quote": "打算持有1年"},
        ],
        "我的预算是10万，打算持有1年",
    )

    assert len(saved) == 1
    assert profile.budget_amount == 100000
    assert profile.holding_period == "1年"

    # 数字对不上 → 丢弃（模型把 "10万" 写成 1000 时不得落库）
    context2, saved2 = build_memory_context(UserProfileCard(customer_id="CUST002"))
    context2.apply_model_facts(
        "CUST002",
        [{"field": "budget_amount", "value": "1000", "quote": "我的预算是10万"}],
        "我的预算是10万",
    )
    assert saved2 == []


def test_model_investment_goal_must_be_supported_by_quote():
    profile = UserProfileCard(customer_id="CUST001")
    context, saved = build_memory_context(profile)

    context.apply_model_facts(
        "CUST001",
        [{"field": "investment_goal", "value": "翻倍", "quote": "我想稳健增值"}],
        "我想稳健增值",
    )

    assert saved == []
    assert profile.investment_goal == ""
