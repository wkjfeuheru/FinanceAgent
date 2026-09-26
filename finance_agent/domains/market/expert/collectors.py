"""市场级数据的聚合取数工具（指数 / 市场宽度 / 资金面 / 政策事件）。

供市场专家采集工具使用：把 provider 的原始记录整理成结构化快照。与 ``stockdata`` 的差异：

- 这里的数据不进入研究评分与可重放证据（不生成 ``FactSnapshot``），只做展示；
- 每项取数都 best-effort，单项失败只在该项标注 ``error``，不影响其余项；
- 指数以**固定清单**（上证/深证成指/创业板指/科创50/沪深300/中证500/中证1000）
  查询，避免每次取全市场 500+ 指数。

金额单位：北向资金为**亿元**（沿用东财口径）。
"""

from __future__ import annotations

from typing import Any, Callable

from finance_agent.infrastructure.market_data.board_codes import INDEX_SYMBOLS
from finance_agent.infrastructure.market_data.provider_manager import get_provider_manager

# 大盘概览关注的宽基指数（规范符号 → 中文名）。
_OVERVIEW_INDICES = (
    "sh000001", "sz399001", "sz399006", "sh000688",
    "sh000300", "sh000905", "sh000852",
)

# ── 政策事件确定性筛选词表 ────────────────────────────────────────────────
# 类目 → 触发关键词。任一关键词命中标题即视为政策类事件；多类命中取**优先级
# 靠前**的类目（表序即优先级）。筛选必须确定性可测，不依赖 LLM。
_POLICY_CATEGORIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("货币政策", (
        "降准", "降息", "加息", "LPR", "逆回购", "MLF", "SLF", "公开市场操作",
        "存款准备金", "再贷款", "再贴现", "货币政策", "流动性", "利率",
    )),
    ("财政政策", (
        "专项债", "特别国债", "国债", "减税", "降费", "退税", "财政政策", "赤字率",
        "中央预算", "转移支付", "贴息", "政府债券",
    )),
    ("资本市场监管", (
        "证监会", "交易所", "上交所", "深交所", "北交所", "新规", "注册制",
        "退市", "减持", "回购", "分红", "信息披露", "立案", "处罚", "IPO",
    )),
    ("产业政策", (
        "规划", "补贴", "纲要", "指导意见", "实施方案", "试点", "国产替代",
        "新质生产力", "专项行动", "扶持", "产业政策", "白名单",
    )),
    ("地产政策", (
        "楼市", "房地产", "限购", "限贷", "房贷", "公积金", "保交楼",
        "城中村", "保障房", "公积金贷款",
    )),
    ("对外开放", (
        "关税", "出口管制", "贸易", "自贸区", "对外开放", "外资", "准入",
        "跨境", "汇率", "人民币国际化",
    )),
)


def _safe(fetch: Callable[[], Any]) -> tuple[Any, str]:
    """执行取数，把异常转为 ``(None, error_text)``；不向上抛。"""
    try:
        return fetch(), ""
    except Exception as exc:  # noqa: BLE001 - 展示层 best-effort
        return None, str(exc)


def _pct_change(closes: list[float], lookback: int) -> float | None:
    """计算近 ``lookback`` 个交易日区间涨跌幅（%）；样本不足返回 None。"""
    if len(closes) <= lookback:
        return None
    base = closes[-1 - lookback]
    if base <= 0:
        return None
    return round((closes[-1] / base - 1) * 100, 2)


def _index_quote(manager: Any, symbol: str) -> dict[str, Any]:
    """取单只指数最新一根日线、成交额与近 5/20 日区间涨跌。"""
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
    # 区间涨跌需要更长历史，单独收集近 21 根收盘价。
    long_closes: list[float] = []
    for row in rows[-21:]:
        try:
            long_closes.append(float(row.get("close")))
        except (TypeError, ValueError):
            continue
    pct_chg = None
    if len(closes) >= 2:
        pct_chg = round((closes[-1] / closes[-2] - 1) * 100, 2)
    amount = latest.get("amount")
    try:
        amount = float(amount) if amount is not None else None
    except (TypeError, ValueError):
        amount = None
    return {
        "symbol": symbol,
        "name": INDEX_SYMBOLS.get(symbol, symbol),
        "as_of": latest.get("trade_date"),
        "close": closes[-1] if closes else None,
        "pct_chg": pct_chg,
        "pct_5d": _pct_change(long_closes, 5),
        "pct_20d": _pct_change(long_closes, 20),
        "amount": amount,
        "recent_closes": closes,
    }


def get_market_overview_data() -> dict[str, Any]:
    """大盘概览：主要指数最新价/涨跌幅/成交额/区间涨跌 + 市场宽度。"""
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
        "note": "指数为最近交易日收盘；宽度为最近交易日快照；区间涨跌按交易日计算。",
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
    """资金面：两市融资融券（日频主指标，含日环比）+ 北向持股市值（季度参考）。

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


def _classify_policy_event(title: str) -> str | None:
    """按优先级返回标题命中的政策类目；未命中返回 None。"""
    for category, keywords in _POLICY_CATEGORIES:
        if any(keyword in title for keyword in keywords):
            return category
    return None


def _within_window(stamp: str, cutoff_iso: str) -> bool:
    """判断时间戳是否在窗口内（按 ISO 日期前缀文本比较，确定性）。

    数据源时间戳格式不一（``2026-09-13 11:21:13`` / ``2026-09-12``），统一取前
    10 位日期比较；无法解析日期的记录一律保留，避免误丢。
    """
    prefix = str(stamp or "").strip()[:10]
    if len(prefix) != 10 or not prefix[4] == "-":
        return True
    return prefix >= cutoff_iso


def get_policy_events_data() -> dict[str, Any]:
    """政策事件：确定性筛选近 N 天政策类快讯并按类目归类。

    取数 best-effort（失败记入 ``limitations``）；筛选完全确定性（日期窗口 +
    关键词词表 + 类目优先级），不调用 LLM。返回按时间倒序的 ``events`` 与各类目
    计数 ``categories_summary``，供专家层做定性解读或纯清单展示。
    """
    from datetime import datetime, timedelta

    from finance_agent.infrastructure import settings as config

    max_days = max(1, int(getattr(config, "POLICY_NEWS_MAX_DAYS", 3)))
    max_items = max(1, int(getattr(config, "POLICY_NEWS_MAX_ITEMS", 50)))
    cutoff_iso = (datetime.now() - timedelta(days=max_days)).strftime("%Y-%m-%d")

    manager = get_provider_manager()
    limitations: list[str] = []
    raw, error = _safe(manager.get_policy_news)
    if error or not raw:
        limitations.append("policy_news")
        raw = []

    events: list[dict[str, Any]] = []
    categories_summary: dict[str, int] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        stamp = str(item.get("datetime") or "").strip()
        if not _within_window(stamp, cutoff_iso):
            continue
        category = _classify_policy_event(title)
        if category is None:
            continue
        events.append({"datetime": stamp, "title": title, "category": category})
        categories_summary[category] = categories_summary.get(category, 0) + 1
        if len(events) >= max_items:
            break

    # 取数成功但无政策类事件不是"限制"，而是诚实的空态。
    return {
        "as_of": (events[0].get("datetime") if events else ""),
        "events": events,
        "categories_summary": categories_summary,
        "window_days": max_days,
        "limitations": limitations,
        "note": f"政策事件按关键词确定性筛选（近 {max_days} 天财经快讯），非全量新闻。",
    }


__all__ = [
    "get_capital_flow_data",
    "get_market_overview_data",
    "get_market_sentiment_data",
    "get_policy_events_data",
]
