"""A 股报告期推算。

用于把"按报告期查询"的数据接口（如东财业绩报表 ``stock_yjbb_em``）对齐到最近
一个**已结束**的报告期。A 股报告期固定为 03-31 / 06-30 / 09-30 / 12-31。

注意这里只判断"报告期是否已结束"，不判断"是否已披露"：季末刚过时对应报表可能
尚未发布，调用方需要向前回退报告期（见 ``recent_report_periods``）。
"""

from __future__ import annotations

from datetime import date

_REPORT_MONTH_DAYS = ((12, 31), (9, 30), (6, 30), (3, 31))


def latest_report_period(today: date) -> str:
    """返回不晚于 ``today`` 的最近报告期，格式 ``YYYYMMDD``。"""
    for month, day in _REPORT_MONTH_DAYS:
        candidate = date(today.year, month, day)
        if candidate <= today:
            return candidate.strftime("%Y%m%d")
    # 年初至 3-31 之前：最近的是上一年年报。
    return f"{today.year - 1}1231"


def _previous_period(period_end: date) -> date:
    """返回上一个报告期的结束日。"""
    month = period_end.month
    if month == 3:
        return date(period_end.year - 1, 12, 31)
    if month == 6:
        return date(period_end.year, 3, 31)
    if month == 9:
        return date(period_end.year, 6, 30)
    return date(period_end.year, 9, 30)


def recent_report_periods(today: date, count: int = 4) -> list[str]:
    """返回自最近报告期起、向前回退的 ``count`` 个报告期（新的在前）。

    用于"最近一期报表尚未发布"时的回退查询：调用方按顺序尝试，取第一个非空。
    """
    latest = latest_report_period(today)
    cursor = date(int(latest[:4]), int(latest[4:6]), int(latest[6:]))
    periods: list[str] = []
    for _ in range(max(1, count)):
        periods.append(cursor.strftime("%Y%m%d"))
        cursor = _previous_period(cursor)
    return periods


__all__ = ["latest_report_period", "recent_report_periods"]
