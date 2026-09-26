"""数据质量门禁测试：新鲜度、基本面溯源、来源一致性与跨期检查。"""

from __future__ import annotations

from datetime import date

from finance_agent.domains.research.contracts import AnalysisKind, AnalysisRequest
from finance_agent.domains.research.quality_gates import (
    GateConfig,
    fundamental_provenance,
    mixed_report_periods,
    quote_freshness,
    source_consistency,
    valuation_basis,
    weekday_trading_days,
)
from finance_agent.domains.research.rule_engine import RuleEngine
from finance_agent.domains.research.snapshot_builder import SnapshotBuilder

EVALUATED_AT = "2026-09-11T08:00:00+00:00"


def _security(
    code: str = "600519",
    *,
    quote_date: str = "2026-09-10",
    fetched_at: str = "2026-09-10T08:00:00+00:00",
    history_dates: bool = True,
    quote_source: str = "fixture",
    history_source: str = "fixture",
    indicators_source: str = "fixture",
    **indicators,
) -> dict:
    closes = [round(10.0 * 1.004 ** index, 4) for index in range(60)]
    rows = [
        {"date": "2026-09-10", "close": close, "high": close * 1.01, "low": close * 0.99}
        if history_dates else {"close": close}
        for close in closes
    ]
    payload = {
        "roe": 18.0, "revenue_yoy": 20.0, "netprofit_yoy": 20.0, "pe_ttm": 18.0, "pb": 2.0,
        "end_date": "2026-06-30", "ann_date": "2026-08-25",
        **indicators,
    }
    payload.update({"source": indicators_source, "fetched_at": fetched_at})
    quote: dict = {"code": code, "price": closes[-1], "adjustment": "raw",
                   "source": quote_source, "fetched_at": fetched_at}
    if quote_date:
        quote["date"] = quote_date
    return {
        "basic_info": {"code": code, "name": f"测试{code}"},
        "quote": quote,
        "history": {"adjustment": "forward", "source": history_source,
                    "fetched_at": fetched_at, "data": rows},
        "indicators": payload,
    }


class Gateway:
    """按代码返回可控的原始取数字段。"""

    def __init__(self, payloads: dict[str, dict]):
        self._payloads = payloads

    def get_security_data(self, stock_code: str) -> dict:
        return self._payloads[stock_code]


def _build(gateway: Gateway, request: AnalysisRequest, **kwargs):
    return SnapshotBuilder(gateway, evaluated_at=None, **kwargs).build(request)


def _single(code: str = "600519") -> AnalysisRequest:
    return AnalysisRequest(kind=AnalysisKind.SINGLE_STOCK, stock_codes=[code])


# ── 新鲜度 ──────────────────────────────────────────────────────


def test_quote_within_allowed_trading_age_is_fresh():
    """上一交易日的数据必须仍然可用（周末与假期不能误判为陈旧）。"""
    request = _single()
    snapshot, _ = _build(Gateway({"600519": _security(fetched_at=EVALUATED_AT)}), request)

    assert snapshot.quality.status == "complete"
    assert snapshot.quality.missing_critical == []
    assert snapshot.quality.warnings == []


def test_stale_quote_is_critical_and_blocks_conclusion():
    """报价超过允许交易日龄时不得再出结论。"""
    request = _single()
    raw = _security(quote_date="2026-09-08", fetched_at=EVALUATED_AT)
    snapshot, facts = _build(Gateway({"600519": raw}), request)
    assessment = RuleEngine.default().evaluate(snapshot, request)

    assert snapshot.quality.status == "critical_missing"
    assert "stale_quote" in snapshot.quality.missing_critical
    assert assessment.action.value == "数据不足"
    assert "stale_quote" in assessment.restrictions
    assert facts[0].payload["provenance"]["quote"]["age_trading_days"] == 3


def test_missing_quote_or_history_date_is_critical():
    """无法证明新鲜度的数据不得静默判为可用。"""
    request = _single()
    snapshot, _ = _build(Gateway({"600519": _security(quote_date="")}), request)

    assert "quote_as_of_missing" in snapshot.quality.missing_critical

    snapshot, _ = _build(Gateway({"600519": _security(history_dates=False)}), request)

    assert "history_as_of_missing" in snapshot.quality.missing_critical


def test_unavailable_provider_calendar_is_disclosed_not_hidden():
    """交易日历降级为工作日估算时必须披露。"""
    def degraded_counter(start: date, end: date) -> tuple[int, str]:
        count, _ = weekday_trading_days(start, end)
        return count, "weekday_fallback"

    request = _single()
    snapshot, _ = _build(
        Gateway({"600519": _security(quote_date="2026-09-10", fetched_at=EVALUATED_AT)}),
        request,
        trading_days=degraded_counter,
    )

    assert "trading_calendar_unavailable" in snapshot.quality.warnings
    assert snapshot.quality.status == "warning"


def test_weekday_counter_reports_its_basis():
    count, basis = weekday_trading_days(date(2026, 9, 10), date(2026, 9, 14))

    assert (count, basis) == (2, "weekday")  # 周五、周一


def test_provider_calendar_counts_real_trading_days(monkeypatch):
    """有交易日历时必须按真实交易日计数（长假不能误判为陈旧）。"""
    from finance_agent.infrastructure.market_data import trading_calendar

    class FakeManager:
        def get_trade_cal(self, start_date: str, end_date: str) -> dict:
            # 2026-10-01 起为长假，只有 10-09 开市。
            return {"data": [
                {"calendar_date": "2026-09-30", "is_trading_day": "1"},
                {"calendar_date": "2026-10-01", "is_trading_day": "0"},
                {"calendar_date": "2026-10-08", "is_trading_day": "0"},
                {"calendar_date": "2026-10-09", "is_trading_day": "1"},
            ]}

    trading_calendar.clear_cache()
    monkeypatch.setattr(trading_calendar, "_manager_factory", lambda: FakeManager(), raising=False)

    count, basis = trading_calendar.trading_days_between(date(2026, 9, 30), date(2026, 10, 9))

    assert (count, basis) == (1, "provider")
    trading_calendar.clear_cache()


def test_provider_calendar_failure_falls_back_and_is_marked(monkeypatch):
    """日历取数失败必须回退工作日计数并显式标记，不能假装是真实交易日。"""
    from finance_agent.infrastructure.market_data import trading_calendar

    class BrokenManager:
        def get_trade_cal(self, start_date: str, end_date: str) -> dict:
            raise RuntimeError("provider down")

    trading_calendar.clear_cache()
    monkeypatch.setattr(trading_calendar, "_manager_factory", lambda: BrokenManager(), raising=False)

    count, basis = trading_calendar.trading_days_between(date(2026, 9, 30), date(2026, 10, 9))

    assert basis == "weekday_fallback"
    assert count > 1
    trading_calendar.clear_cache()


def test_freshness_unit_keeps_hard_gate_threshold():
    reasons, provenance = quote_freshness(
        "2026-09-10", evaluated_at="2026-09-11T08:00:00+00:00", config=GateConfig(),
    )

    assert reasons == []
    assert provenance["age_trading_days"] == 1
    assert provenance["trading_calendar"] == "weekday"


# ── 基本面溯源 ──────────────────────────────────────────────────


def test_missing_report_period_and_disclosure_date_degrade_to_warning():
    """缺报告期/披露日不能再显示 complete，但结论不被阻断。"""
    request = _single()
    raw = _security(end_date=None, ann_date=None, fetched_at=EVALUATED_AT)
    snapshot, _ = _build(Gateway({"600519": raw}), request)
    assessment = RuleEngine.default().evaluate(snapshot, request)

    assert snapshot.quality.status == "warning"
    assert "fundamental_report_period_missing" in snapshot.quality.warnings
    assert "fundamental_disclosure_date_missing" in snapshot.quality.warnings
    assert assessment.action.value != "数据不足"
    assert "fundamental_report_period_missing" in assessment.restrictions


def test_stale_report_period_and_odd_disclosure_dates_are_reported():
    request = _single()
    raw = _security(end_date="2024-06-30", ann_date="2024-01-31", fetched_at=EVALUATED_AT)
    snapshot, _ = _build(Gateway({"600519": raw}), request)

    assert "stale_fundamental_report_period" in snapshot.quality.warnings
    assert "fundamental_disclosure_before_period" in snapshot.quality.warnings


def test_disclosure_date_in_the_future_is_reported():
    request = _single()
    raw = _security(ann_date="2026-12-31", fetched_at=EVALUATED_AT)
    snapshot, _ = _build(Gateway({"600519": raw}), request)

    assert "fundamental_disclosure_in_future" in snapshot.quality.warnings


def test_valuation_basis_distinguishes_ttm_static_and_missing():
    assert valuation_basis({"pe_ttm": 18.0, "pe": 20.0}) == "ttm"
    assert valuation_basis({"pe": 20.0}) == "static"
    assert valuation_basis({"pb": 2.0}) == "missing"

    warnings, provenance = fundamental_provenance(
        {"pe": 20.0, "end_date": "2026-06-30"},
        evaluated_at=EVALUATED_AT, config=GateConfig(),
    )

    assert "valuation_not_ttm" in warnings
    assert provenance["valuation_basis"] == "static"


# ── 来源一致性与跨期 ────────────────────────────────────────────


def test_mixed_sources_are_disclosed():
    assert source_consistency({"quote": "akshare", "history": "akshare"}) == []
    assert source_consistency({"quote": "akshare", "history": "baostock"}) == ["mixed_sources"]
    # 取数失败的空来源不应被误判为跨源。
    assert source_consistency({"quote": "akshare", "history": "unavailable"}) == []

    request = _single()
    raw = _security(history_source="baostock", fetched_at=EVALUATED_AT)
    snapshot, facts = _build(Gateway({"600519": raw}), request)

    assert "mixed_sources" in snapshot.quality.warnings
    assert facts[0].payload["provenance"]["history"]["source"] == "baostock"


def test_comparison_with_mixed_report_periods_is_critical():
    """比较请求混用报告期必须被拒绝，而不是给出跨期结论。"""
    request = AnalysisRequest(kind=AnalysisKind.COMPARISON, stock_codes=["600519", "600036"])
    gateway = Gateway({
        "600519": _security("600519", fetched_at=EVALUATED_AT),
        "600036": _security("600036", end_date="2026-03-31", ann_date="2026-04-25",
                           fetched_at=EVALUATED_AT),
    })
    snapshot, facts = _build(gateway, request)
    assessment = RuleEngine.default().evaluate(snapshot, request)

    assert snapshot.quality.status == "critical_missing"
    assert "mixed_report_period" in snapshot.quality.missing_critical
    assert assessment.action.value == "数据不足"
    assert facts[0].payload["cross_security_reasons"] == ["mixed_report_period"]
    assert mixed_report_periods({"600519": "2026-06-30"}) == []


def test_static_pe_key_is_recognised_as_static_basis():
    """``pe_lyr`` 是静态 PE 的规范键，必须被识别。

    适配器现在把东财的 ``PE(静)`` 映射为 ``pe_lyr``、``PE(TTM)`` 映射为 ``pe_ttm``。
    若 ``valuation_basis`` 只认 ``pe``，那么**只有静态 PE 的数据源会被误判为
    "完全没有估值"**，给出错误的限制提示。
    """
    from finance_agent.domains.research.quality_gates import valuation_basis

    assert valuation_basis({"pe_ttm": 18.0}) == "ttm"
    assert valuation_basis({"pe_ttm": 18.0, "pe_lyr": 20.0}) == "ttm"
    assert valuation_basis({"pe": 20.0}) == "static"
    assert valuation_basis({"pe_lyr": 20.0}) == "static"
    assert valuation_basis({}) == "missing"
    assert valuation_basis({"pe_ttm": None, "pe_lyr": None}) == "missing"
