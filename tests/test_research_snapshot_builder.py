"""市场数据快照构建与质量门禁测试。"""

from datetime import datetime, timezone

from finance_agent.research.contracts import AnalysisKind, AnalysisRequest
from finance_agent.research.snapshot_builder import SnapshotBuilder


class RawHistoryGateway:
    """返回未声明前复权口径的最小数据网关。"""

    def get_security_data(self, stock_code: str) -> dict:
        return {
            "basic_info": {"code": stock_code, "name": "测试股票"},
            "quote": {
                "code": stock_code,
                "price": 10.0,
                "date": "2026-09-10",
                "source": "tushare_mcp",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            },
            "history": {
                "code": stock_code,
                "data": [{"high": 10.5, "low": 9.5, "close": 10.0}] * 60,
                "source": "tushare_mcp",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            },
            "indicators": {"roe": 15.0, "report_period": "2026Q2"},
        }


def test_missing_forward_adjusted_history_is_critical():
    """未声明前复权口径的历史数据不得进入技术面分析。"""
    request = AnalysisRequest(kind=AnalysisKind.SINGLE_STOCK, stock_codes=["600519"])

    snapshot, facts = SnapshotBuilder(RawHistoryGateway()).build(request)

    assert snapshot.quality.status == "critical_missing"
    assert "adjusted_history" in snapshot.quality.missing_critical
    assert facts[0].payload["quality_status"] == "critical_missing"


class FallbackGateway(RawHistoryGateway):
    """返回已批准等价备用源的前复权数据。"""

    def get_security_data(self, stock_code: str) -> dict:
        data = super().get_security_data(stock_code)
        data["quote"].update(
            {
                "source": "baostock",
                "fallback_from": "tushare_mcp",
            }
        )
        data["history"]["adjustment"] = "forward"
        return data


def test_equivalent_fallback_is_visible_in_fact_evidence():
    """切换等价备用源必须形成证据，不能静默降级。"""
    request = AnalysisRequest(kind=AnalysisKind.SINGLE_STOCK, stock_codes=["600519"])

    snapshot, facts = SnapshotBuilder(FallbackGateway()).build(request)

    assert snapshot.securities[0].quote.source == "baostock"
    assert snapshot.securities[0].quote.fallback_from == "tushare_mcp"
    assert any(fact.payload.get("fallback_from") == "tushare_mcp" for fact in facts)
