"""AKShare 行业并入与披露日回填测试（夹具驱动，不联网）。"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest


class _FakeFrame:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def to_dict(self, orient: str = "records"):
        assert orient == "records"
        return self._rows


class _FakeAk:
    """业绩报表按报告期返回夹具；更早报告期返回空，触发向前回退。"""

    def __init__(self, requested: list[str]) -> None:
        self.requested = requested
        self.yjbb = {
            "20260630": [
                {"股票代码": "600519", "所处行业": "白酒Ⅱ", "最新公告日期": "2026-08-15"},
                {"股票代码": "600036", "所处行业": "银行Ⅱ", "最新公告日期": "2026-08-29"},
            ],
        }

    def stock_yjbb_em(self, date: str = ""):
        self.requested.append(date)
        return _FakeFrame(self.yjbb.get(date, []))

    def stock_info_a_code_name(self):
        return _FakeFrame([
            {"code": "600519", "name": "贵州茅台"},
            {"code": "600036", "name": "招商银行"},
        ])

    def stock_financial_analysis_indicator(self, symbol: str = "", start_year: str = ""):
        assert symbol == "600519"
        return _FakeFrame([
            {"日期": "2026-03-31", "净资产收益率(%)": "10.06"},
            {"日期": "2026-06-30", "净资产收益率(%)": "17.72"},
        ])


def _provider(monkeypatch, ak=None):
    from finance_agent.data.akshare_provider import AkshareDataSource

    provider = object.__new__(AkshareDataSource)
    provider.ak = ak or _FakeAk([])
    monkeypatch.setattr("finance_agent.data.akshare_provider.cache_read", lambda *a, **k: None)
    monkeypatch.setattr("finance_agent.data.akshare_provider.cache_write", lambda *a, **k: None)
    return provider


def test_stock_basic_merges_industry_from_earnings_snapshot(monkeypatch):
    monkeypatch.setattr(
        "finance_agent.data.akshare_provider.recent_report_periods",
        lambda today, count=4: ["20260630"],
    )
    provider = _provider(monkeypatch)

    rows = provider.get_stock_basic()

    by_code = {row["code"]: row for row in rows}
    assert by_code["600519"]["industry"] == "白酒Ⅱ"
    assert by_code["600036"]["industry"] == "银行Ⅱ"


def test_financial_indicator_backfills_ann_date_for_latest_period(monkeypatch):
    monkeypatch.setattr(
        "finance_agent.data.akshare_provider.recent_report_periods",
        lambda today, count=4: ["20260630"],
    )
    provider = _provider(monkeypatch)

    rows = provider.get_financial_indicator("600519")

    latest = rows[-1]
    assert latest["end_date"] == "2026-06-30"
    assert latest["ann_date"] == "2026-08-15"
    # 未命中的历史报告期不臆造披露日。
    assert rows[0].get("ann_date") is None


def test_earnings_snapshot_falls_back_to_earlier_period(monkeypatch):
    """最近报告期报表未发布时向前回退，且回退顺序可观测。"""
    requested: list[str] = []
    monkeypatch.setattr(
        "finance_agent.data.akshare_provider.recent_report_periods",
        lambda today, count=4: ["20260930", "20260630", "20260331"],
    )
    provider = _provider(monkeypatch, _FakeAk(requested))

    basic = provider.get_stock_basic("600519")

    assert requested[:2] == ["20260930", "20260630"]   # 20260930 空 → 回退到 20260630
    assert basic[0]["industry"] == "白酒Ⅱ"


def test_snapshot_failure_does_not_block_basic_list(monkeypatch):
    """补全失败时仍返回基础清单（只是不含行业），绝不阻断主流程。"""
    class BrokenAk:
        def stock_yjbb_em(self, date: str = ""):
            raise RuntimeError("upstream down")

        def stock_info_a_code_name(self):
            return _FakeFrame([{"code": "600519", "name": "贵州茅台"}])

    monkeypatch.setattr(
        "finance_agent.data.akshare_provider.recent_report_periods",
        lambda today, count=4: ["20260630"],
    )
    provider = _provider(monkeypatch, BrokenAk())

    rows = provider.get_stock_basic()

    assert rows[0]["code"] == "600519"
    assert not rows[0].get("industry")


def test_financial_indicator_returns_metrics_without_snapshot(monkeypatch):
    """快照不可用时财务指标仍返回，只是缺 ann_date（限制项如实呈现）。"""
    class NoYjbb:
        def stock_financial_analysis_indicator(self, symbol: str = "", start_year: str = ""):
            return _FakeFrame([{"日期": "2026-06-30", "净资产收益率(%)": "17.72"}])

    provider = _provider(monkeypatch, NoYjbb())

    rows = provider.get_financial_indicator("600519")

    assert rows and rows[-1]["roe"] == "17.72"
    assert rows[-1].get("ann_date") is None
