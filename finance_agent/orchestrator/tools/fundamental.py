"""基于 Tushare MCP 的股票数据获取工具。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from langchain_core.tools import tool

from finance_agent.data.tushare_mcp import get_datasource


# 将数据源结果转换为工具可返回的 JSON 字符串。
def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


# 从 Tushare 返回结果中提取记录列表，兼容常见的 data/list/results 包装。
def _records(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("data", "items", "results", "list"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [data]
    return []


# 将单条 Tushare 日线记录转换为统一行情字段。
def _latest_daily_record(data: Any) -> dict[str, Any] | None:
    rows = _records(data)
    if not rows:
        return None
    return rows[-1]


# 从记录中读取第一个非空字段。
def _first_value(record: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = record.get(key)
        if value is not None and value != "":
            return value
    return default


@tool
# 获取最近交易日行情，并合并 Tushare 的估值字段。
def get_stock_quote(stock_code: str) -> str:
    """获取 A 股最近交易日行情与估值概览。"""
    source = get_datasource()
    daily = _latest_daily_record(source.get_daily(stock_code))
    valuation = _latest_daily_record(source.get_daily_basic(stock_code))
    if daily is None:
        return _json({"code": stock_code, "error": "未获取到最近交易日行情"})
    valuation = valuation or {}
    result = {
        "code": stock_code,
        "date": _first_value(daily, "trade_date", "date"),
        "price": _first_value(daily, "close", "price"),
        "change_pct": _first_value(daily, "pct_chg", "change_pct"),
        "change_amount": _first_value(daily, "change_amount", "change"),
        "open": daily.get("open"),
        "high": daily.get("high"),
        "low": daily.get("low"),
        "volume": _first_value(daily, "vol", "volume"),
        "amount": daily.get("amount"),
        "pe": _first_value(valuation, "pe", "pe_ttm"),
        "pb": _first_value(valuation, "pb", "pb_mrq"),
        "ps": _first_value(valuation, "ps", "ps_ttm"),
        "total_market_cap": _first_value(valuation, "total_mv", "total_market_cap"),
        "circ_market_cap": _first_value(valuation, "circ_mv", "circ_market_cap"),
        "source": "tushare_mcp",
    }
    return _json(result)


@tool
# 保留原实时行情工具名，兼容已有调用方。
def get_stock_realtime_quote(stock_code: str) -> str:
    """获取 A 股最近交易日行情，兼容原实时行情工具名。"""
    return get_stock_quote.invoke({"stock_code": stock_code})


@tool
# 获取指定区间的日线历史行情。
def get_stock_history(
    stock_code: str,
    period: str = "daily",
    start_date: str = "",
    end_date: str = "",
) -> str:
    """获取 A 股历史 K 线数据。"""
    if period != "daily":
        return _json({"code": stock_code, "error": "Tushare MCP 当前仅支持 daily 周期"})
    source = get_datasource()
    result = source.get_daily(stock_code, start_date, end_date)
    rows = _records(result)
    normalized = []
    for row in rows:
        normalized.append({
            "date": _first_value(row, "trade_date", "date"),
            "open": row.get("open"),
            "close": row.get("close"),
            "high": row.get("high"),
            "low": row.get("low"),
            "volume": _first_value(row, "vol", "volume"),
            "amount": row.get("amount"),
            "change_pct": _first_value(row, "pct_chg", "change_pct"),
        })
    return _json({"code": stock_code, "count": len(normalized), "data": normalized})


@tool
# 获取 Tushare 财务指标数据。
def get_financial_indicators(stock_code: str) -> str:
    """获取 A 股财务分析指标。"""
    data = get_datasource().get_financial_indicator(stock_code)
    row = _latest_daily_record(data) or {}
    return _json({"code": stock_code, **row, "source": "tushare_mcp"})


@tool
# 获取 A 股基础信息。
def get_stock_basic_info(stock_code: str) -> str:
    """获取 A 股基本信息，包括名称、行业和上市日期。"""
    data = get_datasource().get_stock_basic(stock_code)
    row = _latest_daily_record(data) or {}
    return _json({"code": stock_code, **row, "source": "tushare_mcp"})


@tool
# 获取每日估值指标。
def get_valuation_indicators(stock_code: str) -> str:
    """获取 PE、PB、PS 和市值等估值指标。"""
    data = get_datasource().get_daily_basic(stock_code)
    row = _latest_daily_record(data) or {}
    return _json({"code": stock_code, **row, "source": "tushare_mcp"})


@tool
# 获取利润表数据。
def get_income_statement(stock_code: str) -> str:
    """获取 A 股利润表数据。"""
    data = get_datasource().get_income(stock_code)
    row = _latest_daily_record(data) or {}
    return _json({"code": stock_code, **row, "source": "tushare_mcp"})


# 从用户问题中提取可用于行业或名称匹配的关键词。
def _candidate_keyword(user_query: str) -> str:
    noise_phrases = (
        "帮我推荐", "给我推荐", "请推荐", "值得投资", "值得关注", "投资机会",
        "有哪些", "有什么", "哪些", "什么", "股票", "个股", "行业", "板块",
        "概念", "推荐", "关注", "投资", "的", "吗", "？", "?", "，", ",",
    )
    keyword = str(user_query or "").strip()
    for phrase in sorted(noise_phrases, key=len, reverse=True):
        keyword = keyword.replace(phrase, " ")
    return " ".join(keyword.split()).lower()


@tool
# 按行业或名称关键词搜索候选股票并按近期涨跌幅排序。
def search_candidates(user_query: str, max_results: int = 5) -> str:
    """搜索候选股票，返回代码、名称、行业和筛选理由。"""
    limit = min(max(int(max_results), 1), 10)
    source = get_datasource()
    basics = _records(source.get_stock_basic())
    keyword = _candidate_keyword(user_query)
    keywords = [part for part in keyword.split() if part]
    candidates = []
    for item in basics:
        name = str(_first_value(item, "name", "名称", default=""))
        industry = str(_first_value(item, "industry", "行业", default=""))
        searchable = f"{name} {industry}".lower()
        if keywords and not any(keyword in searchable for keyword in keywords):
            continue
        code = str(_first_value(item, "ts_code", "code", default="")).split(".")[0]
        if not code:
            continue
        daily = _latest_daily_record(source.get_daily(code, (datetime.now() - timedelta(days=15)).strftime("%Y-%m-%d")))
        change_pct = _first_value(daily or {}, "pct_chg", "change_pct", default=0)
        try:
            sort_value = float(change_pct or 0)
        except (TypeError, ValueError):
            sort_value = 0.0
        candidates.append({
            "code": code,
            "name": name,
            "industry": industry,
            "reason": f"匹配行业/名称关键词，近期涨跌幅 {sort_value:+.2f}%",
            "change_pct": change_pct,
        })
        if len(candidates) >= limit * 5:
            break
    candidates.sort(key=lambda item: float(item.get("change_pct") or 0), reverse=True)
    return _json(candidates[:limit])
