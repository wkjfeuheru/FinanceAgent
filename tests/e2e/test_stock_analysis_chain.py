"""股票研究确定性取数回归（面向取数工具与股票专家，无研究管线）。"""

from __future__ import annotations

import json

from finance_agent.orchestration.contracts import BusinessDomain, DomainTaskContext, PlanTask
from finance_agent.orchestration.experts.base import build_expert_graph
from finance_agent.domains.research.expert import stock_tools
from finance_agent.domains.research.expert.stockdata import fetch_stock_data

FETCHED_AT = "2026-08-28T08:00:00+00:00"


def _security(code: str, *, roe: float, rate: float, name: str) -> dict:
    closes = [round(10.0 * (1 + rate) ** index, 4) for index in range(60)]
    return {
        "basic_info": {"code": code, "name": name},
        "quote": {
            "code": code, "price": closes[-1], "date": "2026-08-28",
            "adjustment": "raw", "source": "fixture", "fetched_at": FETCHED_AT,
        },
        "history": {
            "adjustment": "forward", "source": "fixture", "fetched_at": FETCHED_AT,
            "data": [{"date": "2026-08-28", "close": close} for close in closes],
        },
        "indicators": {
            "roe": roe, "revenue_yoy": 20.0, "netprofit_yoy": 20.0,
            "pe_ttm": 18.0, "pb": 2.0, "end_date": "2026-06-30",
            "ann_date": "2026-08-25", "source": "fixture", "fetched_at": FETCHED_AT,
        },
    }


def _stock_data() -> dict:
    return {
        "600519": _security("600519", roe=25.0, rate=0.008, name="贵州茅台"),
        "600036": _security("600036", roe=2.0, rate=-0.004, name="招商银行"),
    }


def _patch_fetch(monkeypatch, data: dict) -> None:
    import finance_agent.domains.research.expert.stockdata as stockdata

    def _quote(stock_code, config=None):
        entry = data.get(stock_code) or {}
        return json.dumps(entry.get("quote") or {"code": stock_code}, ensure_ascii=False)

    monkeypatch.setattr(stockdata, "get_stock_quote", type("T", (), {"invoke": staticmethod(lambda payload: _quote(payload["stock_code"]))})())
    monkeypatch.setattr(stockdata, "get_stock_basic_info", type("T", (), {"invoke": staticmethod(lambda payload: json.dumps((data.get(payload["stock_code"]) or {}).get("basic_info") or {}))})())
    monkeypatch.setattr(stockdata, "get_financial_indicators", type("T", (), {"invoke": staticmethod(lambda payload: json.dumps((data.get(payload["stock_code"]) or {}).get("indicators") or {}))})())
    monkeypatch.setattr(stockdata, "get_valuation_indicators", type("T", (), {"invoke": staticmethod(lambda payload: "{}")})())
    monkeypatch.setattr(stockdata, "get_stock_history", type("T", (), {"invoke": staticmethod(lambda payload: json.dumps((data.get(payload["stock_code"]) or {}).get("history") or {}))})())


def _context(goal: str) -> DomainTaskContext:
    return DomainTaskContext(
        task=PlanTask(
            task_id="single:run-1:stock_research",
            domain=BusinessDomain.STOCK_RESEARCH,
            goal=goal,
            instruction=goal,
            expected_output="domain_outcome",
        ),
        thread_id="v1:CUST1:conv-1",
        customer_id="CUST1",
        conversation_id="conv-1",
        user_message=goal,
    )


def test_fetch_keeps_quote_written_back(monkeypatch):
    data = _stock_data()
    data["600519"]["quote"] = {"price": 1700, "code": "600519"}
    _patch_fetch(monkeypatch, data)

    fetched = fetch_stock_data(["600519"])
    assert fetched["600519"]["quote"] == {"price": 1700, "code": "600519"}


def test_multi_security_fetch_is_independent(monkeypatch):
    _patch_fetch(monkeypatch, _stock_data())
    fetched = fetch_stock_data(["600519", "600036"])
    assert fetched["600519"]["indicators"]["roe"] != fetched["600036"]["indicators"]["roe"]
    assert fetched["600519"]["quote"]["code"] == "600519"
    assert fetched["600036"]["quote"]["code"] == "600036"


def test_stock_expert_emits_quote_fields(monkeypatch):
    from tests.conftest import final_message, make_fake_tool_model, tool_call
    import finance_agent.domains.research.expert.stockdata as stockdata

    class _Provider:
        last_metadata = {"source": "fixture", "fetched_at": FETCHED_AT}

        def get_daily(self, *args, **kwargs):
            return [{"trade_date": "2026-08-28", "close": 1700.0, "pct_chg": 1.2, "open": 1690, "high": 1710, "low": 1680}]

        def get_daily_basic(self, *args, **kwargs):
            return [{"pe_ttm": 18.0, "pb": 2.0}]

    monkeypatch.setattr(stockdata, "get_provider_manager", lambda: _Provider())
    model = make_fake_tool_model([
        tool_call("get_stock_quote", {"stock_code": "600519"}),
        final_message("贵州茅台报价已取到。"),
    ])
    graph = build_expert_graph(
        BusinessDomain.STOCK_RESEARCH,
        tools=stock_tools(),
        system_prompt="json",
        max_steps=6,
        model=model,
    )

    outcome = graph.invoke({"context": _context("分析600519")})["domain_outcome"]

    assert outcome.domain is BusinessDomain.STOCK_RESEARCH
    quote = (outcome.structured_data.get("quotes") or {}).get("600519") or {}
    assert quote.get("price") == 1700.0
    assert outcome.summary == "贵州茅台报价已取到。"
