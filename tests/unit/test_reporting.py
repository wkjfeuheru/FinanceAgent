"""A 股报告期推算测试（跨季末/年初边界）。"""

from datetime import date

from finance_agent.domains.research.reporting_periods import latest_report_period, recent_report_periods


def test_latest_period_just_after_quarter_end():
    assert latest_report_period(date(2026, 9, 12)) == "20260630"
    assert latest_report_period(date(2026, 10, 25)) == "20260930"
    assert latest_report_period(date(2026, 4, 1)) == "20260331"


def test_latest_period_at_exact_quarter_end_includes_that_period():
    assert latest_report_period(date(2026, 3, 31)) == "20260331"
    assert latest_report_period(date(2026, 6, 30)) == "20260630"
    assert latest_report_period(date(2026, 12, 31)) == "20261231"


def test_latest_period_before_first_quarter_end_falls_back_to_prior_year():
    """1—3 月尚未到一季报期，最近的应是上一年年报。"""
    assert latest_report_period(date(2027, 2, 1)) == "20261231"
    assert latest_report_period(date(2027, 3, 30)) == "20261231"


def test_recent_periods_walk_back_by_quarter():
    assert recent_report_periods(date(2026, 9, 12), 4) == [
        "20260630", "20260331", "20251231", "20250930",
    ]
    # 年初回退需跨年
    assert recent_report_periods(date(2027, 2, 1), 3) == [
        "20261231", "20260930", "20260630",
    ]


def test_recent_periods_count_is_at_least_one():
    assert recent_report_periods(date(2026, 9, 12), 0) == ["20260630"]
