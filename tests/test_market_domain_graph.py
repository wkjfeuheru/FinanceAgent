"""市场领域子图：四采集器渲染、模式选择与领域隔离。"""

from __future__ import annotations

import logging

from finance_agent.orchestrator.contracts import BusinessDomain, DomainTaskContext, PlanTask
from finance_agent.orchestrator.domains.base import DomainOperation
from finance_agent.orchestrator.domains.market import MODE_COLLECTORS, build_market_domain_graph, collector_for, run_market_mode


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


def test_collector_for_binds_real_callables_and_rejects_unknown_mode():
    """取数函数解析必须直接返回绑定对象；未知模式返回 None 而非静默降级。"""
    for mode, collector in MODE_COLLECTORS.items():
        assert callable(collector)
        assert collector_for(mode) is collector

    assert collector_for("fx_flow") is None
    # 显式注入表优先于默认绑定表（测试注入入口）。
    sentinel = lambda: {}
    assert collector_for("fx_flow", {"fx_flow": sentinel}) is sentinel


def test_domain_operation_failure_is_logged_and_mapped_to_safe_limitation(caplog):
    """统一错误出口：向用户只暴露安全标识，异常细节必须进日志以便归因。"""
    def _boom(context):
        raise RuntimeError("market data source down")

    graph = build_market_domain_graph([
        DomainOperation(
            name="get_market_overview_data",
            modes=frozenset({"market_overview"}),
            handler=_boom,
        )
    ])

    with caplog.at_level(logging.ERROR):
        outcome = graph.invoke({"context": _context("今天大盘怎么样")})["domain_outcome"]

    assert outcome.status == "failed"
    assert outcome.limitations == ["tool_failed:get_market_overview_data"]
    assert "domain_operation_failed" in caplog.text
    assert "get_market_overview_data" in caplog.text
