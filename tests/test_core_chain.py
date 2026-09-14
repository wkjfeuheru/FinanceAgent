"""股票研究确定性链路回归测试（面向领域子图与公共输出）。"""

from finance_agent.orchestrator.contracts import BusinessDomain, DomainTaskContext, PlanTask
from finance_agent.orchestrator.domains.stock import StockDeps, build_stock_domain_graph, handle_single_stock


def history_fixture(length=40, start=10.0, step=0.2):
    """生成可复现的最小日线数据。"""
    return {
        "data": [
            {
                "date": f"2024-01-{index + 1:02d}",
                "open": start + index * step,
                "high": start + index * step + 0.5,
                "low": start + index * step - 0.5,
                "close": start + index * step,
                "volume": 1000,
            }
            for index in range(length)
        ]
    }


def stock_data_fixture():
    return {
        "600519": {
            "basic_info": {"name": "贵州茅台"},
            "indicators": {"roe": 20, "pe": 25},
            "history": history_fixture(start=100),
        },
        "000001": {
            "basic_info": {"name": "平安银行"},
            "indicators": {"roe": 10, "pe": 8},
            "history": history_fixture(start=12, step=0.05),
        },
    }


def _context(goal: str, instruction: str = "") -> DomainTaskContext:
    return DomainTaskContext(
        task=PlanTask(
            task_id="single:run-1:stock_research",
            domain=BusinessDomain.STOCK_RESEARCH,
            goal=goal,
            instruction=instruction or goal,
            expected_output="domain_outcome",
        ),
        thread_id="v1:CUST1:conv-1",
        customer_id="CUST1",
        conversation_id="conv-1",
        user_message=goal,
    )


def test_stock_single_lookup_keeps_quote_and_candidate():
    """单股取数结果必须能写回完整股票条目。"""
    data = stock_data_fixture()
    data["600519"]["quote"] = {"price": 1700}
    data["600519"]["search_candidate"] = {"source": "fixture"}

    result = handle_single_stock(StockDeps(), "600519", stock_data=data)

    assert result["code"] == "600519"
    assert result["quote"] == {"price": 1700}
    assert result["search_candidate"] == {"source": "fixture"}


class _FakePipeline:
    def analyze_per_security(self, request, *, user_profile):
        from finance_agent.research.contracts import (
            Action,
            AnalysisKind,
            AnalysisRequest,
            AnalysisResult,
        )

        results = [
            AnalysisResult(
                request=AnalysisRequest(kind=AnalysisKind.SINGLE_STOCK, stock_codes=[code]),
                action=Action.WATCH,
                data_quality="complete",
                rule_version="research_rules/v1",
                narrative=f"{code} 研究结论：观望。",
            )
            for code in request.stock_codes
        ]
        return results, []


def test_stock_domain_graph_emits_uniform_outcome_and_stock_fields():
    graph = build_stock_domain_graph(StockDeps(pipeline=_FakePipeline(), injected_pipeline=True))

    outcome = graph.invoke({"context": _context("分析600519")})["domain_outcome"]

    assert outcome.domain is BusinessDomain.STOCK_RESEARCH
    assert "600519" in outcome.structured_data["stock_analysis"]
    assert outcome.structured_data["analysis_results"]
