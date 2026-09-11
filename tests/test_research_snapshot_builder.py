"""市场数据快照构建与质量门禁测试。"""

from datetime import date, datetime, timedelta, timezone

from finance_agent.research.contracts import AnalysisKind, AnalysisRequest
from finance_agent.research.rule_engine import RuleEngine
from finance_agent.research.snapshot_builder import SnapshotBuilder

# 新鲜度门禁按交易日比较数据日期与评估时点，夹具必须自带自洽的日期。
FIXTURE_DAY = "2026-09-10"
FIXTURE_FETCHED_AT = "2026-09-10T08:00:00+00:00"


def _bar_dates(count: int, last: str = FIXTURE_DAY) -> list[str]:
    """生成 count 个连续自然日，最后一根为 last。"""
    end = date.fromisoformat(last)
    return [(end - timedelta(days=count - 1 - index)).isoformat() for index in range(count)]


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


class RawMetricsGateway:
    """仅提供生产取数层可获得的原始字段。"""

    def get_security_data(self, stock_code: str) -> dict:
        closes = [100.0 + index for index in range(60)]
        dates = _bar_dates(len(closes))
        return {
            "basic_info": {"code": stock_code, "name": "原始指标股票"},
            "quote": {
                "code": stock_code,
                "price": closes[-1],
                "date": FIXTURE_DAY,
                "adjustment": "raw",
                "source": "fixture",
                "fetched_at": FIXTURE_FETCHED_AT,
            },
            "history": {
                "adjustment": "forward",
                "as_of": FIXTURE_DAY,
                "source": "fixture",
                "fetched_at": FIXTURE_FETCHED_AT,
                "data": [
                    {"date": day, "close": close, "high": close + 1.0, "low": close - 1.0}
                    for day, close in zip(dates, closes)
                ],
            },
            "indicators": {
                "roe": 18.0,
                "revenue_yoy": 20.0,
                "netprofit_yoy": 20.0,
                "pe_ttm": 18.0,
                "pb": 2.0,
                "end_date": "2026-06-30",
                "ann_date": "2026-08-25",
                "source": "fixture",
                "fetched_at": FIXTURE_FETCHED_AT,
                "fundamental_score": 1.0,
                "technical_score": 2.0,
                "risk_score": 3.0,
            },
        }


def test_raw_metrics_are_converted_to_research_scores():
    """快照必须从原始财务和 K 线字段生成规则引擎需要的评分。"""
    request = AnalysisRequest(kind=AnalysisKind.SINGLE_STOCK, stock_codes=["600519"])

    snapshot, _ = SnapshotBuilder(RawMetricsGateway()).build(request)
    indicators = snapshot.securities[0].indicators
    assessment = RuleEngine.default().evaluate(snapshot, request)

    assert indicators["fundamental_score"] > 50.0
    assert indicators["technical_score"] > 50.0
    assert indicators["risk_score"] > 50.0
    assert assessment.action.value != "数据不足"


class MissingRawMetricsGateway(RawMetricsGateway):
    """缺失所有财务指标与有效价格时不能得到占位分数。"""

    def get_security_data(self, stock_code: str) -> dict:
        data = super().get_security_data(stock_code)
        data["indicators"] = {}
        data["history"]["data"] = [{"close": None}] * 60
        return data


def test_missing_raw_metrics_do_not_create_placeholder_scores():
    """原始数据不足应保留空分数并让规则层降级。"""
    request = AnalysisRequest(kind=AnalysisKind.SINGLE_STOCK, stock_codes=["600519"])

    snapshot, _ = SnapshotBuilder(MissingRawMetricsGateway()).build(request)
    indicators = snapshot.securities[0].indicators
    assessment = RuleEngine.default().evaluate(snapshot, request)

    assert indicators["fundamental_score"] is None
    assert indicators["technical_score"] is None
    assert indicators["risk_score"] is None
    assert "fundamental_metrics" in indicators["score_restrictions"]
    assert "price_history" in indicators["score_restrictions"]
    assert assessment.action.value == "数据不足"
