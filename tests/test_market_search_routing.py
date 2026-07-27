from finance_agent.agents.supervisor import (
    SupervisorAgent,
    needs_market_overview_search,
    needs_stock_screening,
)


def test_sector_ranking_uses_market_overview_search():
    query = "昨天涨幅最高的三个板块是什么？"
    assert needs_market_overview_search(query)
    assert not needs_stock_screening(query)


def test_stock_screening_is_not_market_overview():
    query = "推荐三只人工智能板块股票"
    assert needs_stock_screening(query)
    assert not needs_market_overview_search(query)


def test_market_overview_has_deterministic_plan():
    supervisor = object.__new__(SupervisorAgent)
    result = supervisor.plan_tasks("昨天涨幅最高的三个板块是什么？")
    assert [item["intent"] for item in result["intents"]] == ["market_query"]
    assert result["task_plan"] == ["compliance"]
