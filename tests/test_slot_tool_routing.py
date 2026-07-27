from finance_agent.agents.supervisor import needs_slot_extraction


def test_slot_tool_required_for_structured_business_inputs():
    assert needs_slot_extraction("asset_allocation", "用10万元稳健配置茅台和招行")
    assert needs_slot_extraction("market_query", "分析600519的基本面")
    assert needs_slot_extraction("market_query", "贵州茅台最近走势")
    assert needs_slot_extraction("stock_recommendation", "茅台和五粮液哪个更值得买")


def test_slot_tool_skipped_for_search_and_chat_inputs():
    assert not needs_slot_extraction("market_query", "昨天涨幅最高的三个板块")
    assert not needs_slot_extraction("market_query", "上证指数今天表现如何")
    assert not needs_slot_extraction("stock_recommendation", "推荐三只AI股票")
    assert not needs_slot_extraction("casual_chat", "最近亏得有点焦虑")
