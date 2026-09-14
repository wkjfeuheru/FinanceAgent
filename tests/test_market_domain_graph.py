"""市场领域子图：四采集器渲染、模式选择与领域隔离。"""

from __future__ import annotations

from finance_agent.orchestrator.contracts import BusinessDomain, DomainTaskContext, PlanTask
from finance_agent.orchestrator.domains.base import DomainOperation
from finance_agent.orchestrator.domains.market import build_market_domain_graph, run_market_mode


class _FakeInterpreter:
    def interpret(self, events, as_of, window_days):
        raise AssertionError("policy interpreter must not be called for overview")


def _context(goal: str) -> DomainTaskContext:
    return DomainTaskContext(
        task=PlanTask(
            task_id="single:run-1:market_insight",
            domain=BusinessDomain.MARKET_INSIGHT,
            goal=goal,
            instruction=goal,
            expected_output="domain_outcome",
        ),
        thread_id="v1:CUST1:conv-1",
        customer_id="CUST1",
        conversation_id="conv-1",
        user_message=goal,
    )


_OVERVIEW = {
    "as_of": "2026-09-11",
    "indices": [{"name": "上证指数", "close": 3888.11, "pct_chg": -1.18}],
    "breadth": {"advancing": 604, "declining": 4567, "limit_up": 40, "limit_down": 21},
    "limitations": [],
    "note": "",
}


def test_market_domain_renders_overview_and_produces_uniform_outcome():
    graph = build_market_domain_graph(
        [
            DomainOperation(
                name="get_market_overview_data",
                modes=frozenset({"market_overview"}),
                handler=lambda context: run_market_mode(
                    "market_overview", interpreter=_FakeInterpreter(), collector=lambda: dict(_OVERVIEW)
                ),
            )
        ]
    )

    result = graph.invoke({"context": _context("今天大盘怎么样")})
    outcome = result["domain_outcome"]

    assert outcome.domain == BusinessDomain.MARKET_INSIGHT
    assert outcome.structured_data["mode"] == "market_overview"
    assert "3,888.11" in outcome.summary
    assert result["tool_trace"] == ["get_market_overview_data"]


def test_market_domain_cannot_call_product_tool():
    graph = build_market_domain_graph(
        [
            DomainOperation(
                name="get_market_overview_data",
                modes=frozenset({"market_overview"}),
                handler=lambda context: run_market_mode(
                    "market_overview", interpreter=_FakeInterpreter(), collector=lambda: dict(_OVERVIEW)
                ),
            )
        ]
    )

    result = graph.invoke({"context": _context("今天大盘怎么样")})

    assert "product_lookup" not in result["tool_trace"]


def test_market_domain_unsupported_mode_fails_without_other_domain_tools():
    # 白名单为空时，任何模式都必须安全失败，不得调用别处工具。
    graph = build_market_domain_graph([])

    outcome = graph.invoke({"context": _context("今天大盘怎么样")})["domain_outcome"]

    assert outcome.status == "failed"
    assert any(limitation.startswith("unsupported_mode") for limitation in outcome.limitations)
