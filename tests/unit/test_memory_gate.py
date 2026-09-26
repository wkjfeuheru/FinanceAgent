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
