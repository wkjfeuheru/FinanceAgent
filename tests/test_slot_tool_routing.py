from finance_agent.agents.supervisor import requires_slot_extraction


def test_slot_authorization_uses_plan_not_query_text():
    shared_query = "完全相同的文本"

    assert requires_slot_extraction({
        "intent": "market_query",
        "query": shared_query,
        "execution_mode": "security_analysis",
        "requires_slot_extraction": True,
    })
    assert not requires_slot_extraction({
        "intent": "market_query",
        "query": shared_query,
        "execution_mode": "market_overview",
        "requires_slot_extraction": False,
    })


def test_slot_authorization_rejects_inconsistent_plan():
    assert not requires_slot_extraction({
        "intent": "market_query",
        "query": "分析任意标的",
        "execution_mode": "market_overview",
        "requires_slot_extraction": True,
    })
    assert not requires_slot_extraction({
        "intent": "casual_chat",
        "query": "聊聊",
        "execution_mode": "conversation",
        "requires_slot_extraction": True,
    })


def test_allocation_plan_requires_slot_extraction():
    assert requires_slot_extraction({
        "intent": "asset_allocation",
        "query": "替我安排这笔资金",
        "execution_mode": "allocation",
        "requires_slot_extraction": True,
    })
