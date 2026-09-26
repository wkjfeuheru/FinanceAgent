"""画像读写的降级路径：失败必须降级，不能把整轮打断。

回归的是历史缺陷：``memory.py`` 在 ``except`` 分支里用了未定义的 ``logger``，于是
"读画像失败"变成 ``NameError`` 冒泡——调用方的兜底捕获把它记成一次普通降级，
画像却凭空变成空；写画像失败同样会抛到持久化协作器里。
"""

from __future__ import annotations

from finance_agent.orchestration.memory import AgentMemoryContext, UserProfileCard


def test_profile_read_failure_degrades_to_empty_card():
    def boom(customer_id):
        raise RuntimeError("db down")

    context = AgentMemoryContext(profile_loader=boom)

    profile = context.get_profile("cust001")

    assert isinstance(profile, UserProfileCard)
    assert profile.customer_id == "CUST001"
    assert profile.risk_preference == ""


def test_profile_write_failure_returns_false_without_raising(monkeypatch):
    context = AgentMemoryContext(
        profile_loader=lambda customer_id: {"customer_id": customer_id},
    )

    class _BrokenDB:
        def save_profile(self, payload):
            raise RuntimeError("db down")

    monkeypatch.setattr(
        "finance_agent.orchestration.memory.get_database", lambda: _BrokenDB(),
    )
    card = UserProfileCard(customer_id="CUST001", risk_preference="R2 中低风险")

    assert context.save_profile(card) is False


def test_explicit_risk_phrasing_maps_specific_levels_first():
    """"中高风险"含"高风险"：更具体的取值必须先匹配，否则会被记成 R5。"""
    context = AgentMemoryContext(profile_loader=lambda customer_id: {"customer_id": customer_id})

    cases = {
        "我的风险偏好是中高风险": "R4 中高风险",
        "我的风险偏好是中低风险": "R2 中低风险",
        "我的风险偏好是高风险": "R5 高风险",
        "我的风险偏好是低风险": "R1 低风险",
        "我的风险偏好是中风险": "R3 中风险",
    }
    for message, expected in cases.items():
        candidates = context.extract_profile_candidates(message)
        values = [c.value for c in candidates if c.field == "risk_preference"]
        assert values == [expected], f"{message} → {values}"
