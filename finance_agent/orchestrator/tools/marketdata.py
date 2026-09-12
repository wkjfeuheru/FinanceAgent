"""市场级数据的聚合取数工具（指数 / 市场宽度 / 北向资金）。

供 ``MarketInsightAgent`` 使用：把 provider 的原始记录整理成**展示层可直接渲染**
的结构化快照。与 ``stockdata`` 的差异：

- 这里的数据不进入研究评分与可重放证据（不生成 ``FactSnapshot``），只做展示；
- 每项取数都 best-effort，单项失败只在该项标注 ``error``，不影响其余项；
- 指数以**固定清单**（上证/深证成指/创业板指/科创50/沪深300）查询，避免每次
  取全市场 500+ 指数。

金额单位：北向资金为**亿元**（沿用东财口径）。
"""

from __future__ import annotations

from typing import Any, Callable

from finance_agent.data.board_codes import INDEX_SYMBOLS
from finance_agent.data.provider_manager import get_provider_manager

# 大盘概览关注的宽基指数（规范符号 → 中文名）。
_OVERVIEW_INDICES = ("sh000001", "sz399001", "sz399006", "sh000688", "sh000300")


def _safe(fetch: Callable[[], Any]) -> tuple[Any, str]:
    """执行取数，把异常转为 ``(None, error_text)``；不向上抛。"""
    try:
        return fetch(), ""
    except Exception as exc:  # noqa: BLE001 - 展示层 best-effort
        return None, str(exc)


def _index_quote(manager: Any, symbol: str) -> dict[str, Any]:
    """取单只指数最新一根日线与近 5 日走势。"""
    rows = manager.get_index_daily(symbol)
    latest = rows[-1] if rows else {}
    recent = rows[-5:]
    closes = []
    for row in recent:
        close = row.get("close")
        try:
            closes.append(float(close))
        except (TypeError, ValueError):
            continue
    pct_chg = None
    if len(closes) >= 2:
        pct_chg = round((closes[-1] / closes[-2] - 1) * 100, 2)
    return {
        "symbol": symbol,
        "name": INDEX_SYMBOLS.get(symbol, symbol),
        "as_of": latest.get("trade_date"),
        "close": closes[-1] if closes else None,
        "pct_chg": pct_chg,
        "recent_closes": closes,
    }


def get_market_overview_data() -> dict[str, Any]:
    """大盘概览：主要指数最新价与涨跌幅 + 市场宽度 + 成交额。"""
    manager = get_provider_manager()
    indices: list[dict[str, Any]] = []
    limitations: list[str] = []
    for symbol in _OVERVIEW_INDICES:
        quote, error = _safe(lambda s=symbol: _index_quote(manager, s))
        if error or not quote:
            limitations.append(f"index:{symbol}")
            continue
        indices.append(quote)

    breadth, breadth_error = _safe(manager.get_market_breadth)
    if breadth_error or not breadth:
        limitations.append("market_breadth")

    return {
        "as_of": (indices[0].get("as_of") if indices else "") or "",
        "indices": indices,
        "breadth": breadth or {},
        "limitations": limitations,
        "note": "指数为最近交易日收盘；宽度为最近交易日快照。",
    }


def get_market_sentiment_data() -> dict[str, Any]:
    """市场情绪：涨跌家数、涨跌停、活跃度，附主要指数涨跌幅作为交叉参照。"""
    manager = get_provider_manager()
    breadth, breadth_error = _safe(manager.get_market_breadth)
    limitations: list[str] = []
    if breadth_error or not breadth:
        limitations.append("market_breadth")

    benchmark, benchmark_error = _safe(lambda: _index_quote(manager, "sh000001"))
    if benchmark_error or not benchmark:
        limitations.append("index:sh000001")
        benchmark = {}

    return {
        "as_of": (breadth or {}).get("as_of", "") or benchmark.get("as_of", ""),
        "breadth": breadth or {},
        "benchmark": benchmark,
        "limitations": limitations,
        "note": "情绪指标来自全市场涨跌统计，不构成个股建议。",
    }


def get_capital_flow_data() -> dict[str, Any]:
    """资金面：两市融资融券（日频主指标）+ 北向持股市值（季度参考）。

    原北向逐日净买额自 2024-08 起停止披露（监管调整），故改用仍在日频披露的
    融资融券作为主指标，并以季度披露的北向持股市值作为中期参考。两项均
    best-effort，缺项只记入 ``limitations``。
    """
    manager = get_provider_manager()
    limitations: list[str] = []

    margin, margin_error = _safe(manager.get_margin_summary)
    if margin_error or not margin:
        limitations.append("margin_summary")
        margin = {}

    holdings, holdings_error = _safe(manager.get_northbound_holdings)
    if holdings_error or not holdings:
        limitations.append("northbound_holdings")
        holdings = {}

    return {
        "as_of": (margin or {}).get("as_of", "") or "",
        "margin": margin or {},
        "northbound_holdings": holdings or {},
        "limitations": limitations,
        "note": "融资融券为两市合计、交易所日频披露；北向持股市值为季度披露，非实时。",
    }


__all__ = [
    "get_capital_flow_data",
    "get_market_overview_data",
    "get_market_sentiment_data",
]
