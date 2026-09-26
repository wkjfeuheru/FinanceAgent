"""统一数据 Provider 的 LangChain 股票数据工具。

工具层只负责参数校验、调用统一数据接口（ProviderManager）与输出统一 JSON；
具体使用 AKShare / Tushare MCP / BaoStock 中的哪个数据源，由数据层自动路由与降级。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from finance_agent.infrastructure.market_data.provider_manager import get_provider_manager
from finance_agent.orchestration.experts.base import sink_of


# 将数据源结果转换为工具可返回的 JSON 字符串。
def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


# 从 Provider 返回结果中提取记录列表，兼容常见的 data/list/results 包装。
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


# 将单条日线记录（或记录列表）转换为统一行情字段。
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


# 返回最近一次数据请求的来源元数据，供工具层标记数据来源与降级状态。
def _meta() -> dict[str, Any]:
    meta = get_provider_manager().last_metadata
    source = meta.get("source")
    if not source:
        return {"source": "unavailable"}
    result: dict[str, Any] = {
        "source": source,
        "fetched_at": meta.get("fetched_at"),
    }
    if meta.get("degraded"):
        result["degraded"] = True
        result["attempted"] = meta.get("attempted") or []
    return result


def _record_code(config: RunnableConfig | dict | None, tool_name: str, key: str, code: str, payload: dict[str, Any]) -> None:
    sink = sink_of(config)
    if sink is None or not isinstance(payload, dict) or payload.get("error"):
        return
    bucket = dict(sink.structured.get(key) or {})
    bucket[code] = payload
    sink.record(tool_name, payload={key: bucket})


@tool
# 获取最近交易日行情，并合并估值字段。
def get_stock_quote(stock_code: str, config: RunnableConfig) -> str:
    """获取 A 股最近交易日行情与估值概览。"""
    manager = get_provider_manager()
    daily = _latest_daily_record(manager.get_daily(stock_code))
    if daily is None:
        return _json({"code": stock_code, "error": "未获取到最近交易日行情"})
    # 来源元数据必须在行情取数成功后立即读取：估值取数会覆盖 last_metadata。
    meta = _meta()
    # 估值接口并非所有数据源都提供（AKShare/BaoStock 明确不支持）。
    # 估值缺失不能连累行情本身，否则快照会因缺少 quote 被判为关键数据缺失。
    try:
        valuation = _latest_daily_record(manager.get_daily_basic(stock_code)) or {}
    except Exception:
        valuation = {}
    result = {
        "code": stock_code,
        "date": _first_value(daily, "trade_date", "date"),
        "price": _first_value(daily, "close", "price"),
        # 最新报价保持原始口径，必须与快照里的前复权 K 线区分标记。
        "adjustment": "raw",
        "change_pct": _first_value(daily, "pct_chg", "change_pct"),
        "change_amount": _first_value(daily, "change_amount", "change"),
        "open": daily.get("open"),
        "high": daily.get("high"),
        "low": daily.get("low"),
        "volume": _first_value(daily, "vol", "volume"),
        "amount": daily.get("amount"),
        # PE 优先取 TTM，与 research.scoring 的评分输入保持一致；静态 PE（pe_lyr）
        # 不进入报价契约。
        "pe": _first_value(valuation, "pe_ttm", "pe"),
        "pb": _first_value(valuation, "pb", "pb_mrq"),
        "ps": _first_value(valuation, "ps", "ps_ttm"),
        "total_market_cap": _first_value(valuation, "total_mv", "total_market_cap"),
        "circ_market_cap": _first_value(valuation, "circ_mv", "circ_market_cap"),
        **meta,
    }
    _record_code(config, "get_stock_quote", "quotes", stock_code, result)
    return _json(result)


@tool
# 获取指定区间的日线历史行情。
def get_stock_history(
    stock_code: str,
    config: RunnableConfig,
    period: str = "daily",
    start_date: str = "",
    end_date: str = "",
    adjustment: str = "forward",
) -> str:
    """获取 A 股历史 K 线数据。"""
    if period != "daily":
        return _json({"code": stock_code, "error": "当前仅支持 daily 周期"})
    manager = get_provider_manager()
    result = manager.get_daily(stock_code, start_date, end_date, adjustment)
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
    payload = {
        "code": stock_code,
        "count": len(normalized),
        "data": normalized,
        "adjustment": adjustment,
        "as_of": normalized[-1].get("date") if normalized else None,
        "quality_status": "complete" if normalized else "critical_missing",
        **_meta(),
    }
    _record_code(config, "get_stock_history", "history", stock_code, payload)
    return _json(payload)


@tool
# 获取财务指标数据。
def get_financial_indicators(stock_code: str, config: RunnableConfig) -> str:
    """获取 A 股财务分析指标。"""
    data = get_provider_manager().get_financial_indicator(stock_code)
    row = _latest_daily_record(data) or {}
    payload = {"code": stock_code, **row, **_meta()}
    _record_code(config, "get_financial_indicators", "financials", stock_code, payload)
    return _json(payload)


@tool
# 获取 A 股基础信息。
def get_stock_basic_info(stock_code: str, config: RunnableConfig) -> str:
    """获取 A 股基本信息，包括名称、行业和上市日期。"""
    data = get_provider_manager().get_stock_basic(stock_code)
    row = _latest_daily_record(data) or {}
    payload = {"code": stock_code, **row, **_meta()}
    _record_code(config, "get_stock_basic_info", "basics", stock_code, payload)
    return _json(payload)


@tool
# 获取每日估值指标。
def get_valuation_indicators(stock_code: str, config: RunnableConfig) -> str:
    """获取 PE、PB、PS 和市值等估值指标。"""
    data = get_provider_manager().get_daily_basic(stock_code)
    row = _latest_daily_record(data) or {}
    payload = {"code": stock_code, **row, **_meta()}
    _record_code(config, "get_valuation_indicators", "valuations", stock_code, payload)
    return _json(payload)


@tool
# 获取利润表数据。
def get_income_statement(stock_code: str, config: RunnableConfig) -> str:
    """获取 A 股利润表数据。"""
    data = get_provider_manager().get_income(stock_code)
    row = _latest_daily_record(data) or {}
    payload = {"code": stock_code, **row, **_meta()}
    _record_code(config, "get_income_statement", "income", stock_code, payload)
    return _json(payload)


@tool
def match_stock_names(user_query: str, max_results: int = 5) -> str:
    """按官方名称全称、简称或近似文本解析股票候选，不确定时返回歧义而不猜测。"""
    try:
        basics = _records(get_provider_manager().get_stock_basic())
    except Exception:  # noqa: BLE001
        return _json({"error": "名称解析源暂不可用", "candidates": [], "ambiguous_tokens": []})

    items = []
    for row in basics:
        code = str(_first_value(row, "ts_code", "code", "股票代码", "代码", default="") or "")
        name = str(_first_value(row, "name", "名称", default="") or "")
        code = code.split(".", 1)[0].strip()
        name = name.strip()
        if code and name:
            items.append({"code": code, "name": name})

    from finance_agent.shared.name_matching import match_names

    limit = min(max(int(max_results), 1), 10)
    matched = match_names(user_query, items, max_codes=limit)
    return _json({
        "codes": matched.codes,
        "candidates": [
            {"code": candidate.code, "name": candidate.name}
            for candidate in matched.candidates[:limit]
        ],
        "ambiguous_tokens": matched.ambiguous_tokens,
    })


# 从用户问题中提取可用于行业或名称匹配的关键词。
def _candidate_keyword(user_query: str) -> str:
    # 中文没有空格分词，所以"推荐几个白酒股"必须靠剔除填充词还原成"白酒"，
    # 否则整串无法作为子串命中行业（"白酒Ⅱ"）。长词在前，避免"股票"被"股"先截断。
    noise_phrases = (
        "帮我推荐", "给我推荐", "请推荐", "值得投资", "值得关注", "投资机会",
        "有哪些", "有什么", "哪些", "什么", "股票", "个股", "行业", "板块",
        "概念", "推荐", "关注", "投资", "分析", "分析一下", "看看", "走势",
        "行情", "基本面", "技术面", "怎么样", "如何", "最近", "近期",
        "帮我", "给我", "我想", "几个", "几只", "几支", "几档", "一些",
        "龙头", "标的", "股", "只", "支",
        "的", "吗", "？", "?", "，", ",", "、", "和", "与",
    )
    keyword = str(user_query or "").strip()
    for phrase in sorted(noise_phrases, key=len, reverse=True):
        keyword = keyword.replace(phrase, " ")
    return " ".join(keyword.split()).lower()


@tool
# 按行业或名称关键词搜索候选股票并按近期涨跌幅排序。
def search_candidates(user_query: str, config: RunnableConfig, max_results: int = 5) -> str:
    """搜索候选股票，返回代码、名称、行业和筛选理由。

    优先做**名称子串**强匹配（用户问题中出现官方股票名称，如"贵州茅台"），
    无名称命中时再回退到行业/关键词匹配。
    """
    limit = min(max(int(max_results), 1), 10)
    manager = get_provider_manager()
    basics = _records(manager.get_stock_basic())
    query_lower = str(user_query or "").lower()
    keyword = _candidate_keyword(user_query)
    keywords = [part for part in keyword.split() if part]
    candidates = []
    seen_codes = set()

    def _append(code, name, industry, daily, reason):
        if code in seen_codes:
            return
        seen_codes.add(code)
        change_pct = _first_value(daily or {}, "pct_chg", "change_pct", default=0)
        try:
            sort_value = float(change_pct or 0)
        except (TypeError, ValueError):
            sort_value = 0.0
        candidates.append({
            "code": code,
            "name": name,
            "industry": industry,
            "reason": reason.format(sort_value) if "{}" in reason else reason,
            "change_pct": change_pct,
        })

    # 强信号：官方名称直接出现在用户问题中（如"贵州茅台"）
    for item in basics:
        name = str(_first_value(item, "name", "名称", default="")).strip()
        industry = str(_first_value(item, "industry", "行业", default="")).strip()
        code = str(_first_value(item, "ts_code", "code", default="")).split(".")[0].strip()
        if not code or not name:
            continue
        if name.lower() in query_lower:
            daily = _latest_daily_record(manager.get_daily(code, (datetime.now() - timedelta(days=15)).strftime("%Y-%m-%d")))
            _append(code, name, industry, daily, "按股票名称匹配，近期涨跌幅 {:+.2f}%")
        if len(candidates) >= limit * 5:
            break

    # 兜底：行业/名称关键词匹配
    if len(candidates) < limit:
        for item in basics:
            name = str(_first_value(item, "name", "名称", default="")).strip()
            industry = str(_first_value(item, "industry", "行业", default="")).strip()
            searchable = f"{name} {industry}".lower()
            if keywords and not any(kw in searchable for kw in keywords):
                continue
            code = str(_first_value(item, "ts_code", "code", default="")).split(".")[0].strip()
            if not code:
                continue
            daily = _latest_daily_record(manager.get_daily(code, (datetime.now() - timedelta(days=15)).strftime("%Y-%m-%d")))
            change_pct = _first_value(daily or {}, "pct_chg", "change_pct", default=0)
            try:
                sort_value = float(change_pct or 0)
            except (TypeError, ValueError):
                sort_value = 0.0
            _append(code, name, industry, daily, f"匹配行业/名称关键词，近期涨跌幅 {sort_value:+.2f}%")
            if len(candidates) >= limit * 5:
                break

    candidates.sort(key=lambda item: float(item.get("change_pct") or 0), reverse=True)
    selected = candidates[:limit]
    sink = sink_of(config)
    if sink is not None:
        sink.record("search_candidates", payload={"candidates": selected})
    return _json(selected)


def _parse_json_dict(raw: str) -> dict[str, Any]:
    """将工具返回的 JSON 字符串解析为 dict，失败返回空 dict。"""
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def fetch_stock_data(codes: list[str]) -> dict[str, Any]:
    """为给定股票代码拉取基本信息、财务/估值指标、K 线与行情。

    单个数据源不可用时按字段降级，不阻断整体流程；最终由调用方专家
    基于缺失数据给出降级说明。返回结构：
        {code: {"basic_info": ..., "indicators": ..., "history": ..., "quote": ...}}
    """
    stock_data: dict[str, Any] = {}
    for code in codes:
        entry: dict[str, Any] = {}

        try:
            basic = _parse_json_dict(get_stock_basic_info.invoke({"stock_code": code}))
            if basic and "error" not in basic:
                entry["basic_info"] = basic
        except Exception:
            pass

        indicators: dict[str, Any] = {}
        try:
            fina = _parse_json_dict(get_financial_indicators.invoke({"stock_code": code}))
            if fina and "error" not in fina:
                indicators.update(fina)
        except Exception:
            pass
        try:
            valuation = _parse_json_dict(get_valuation_indicators.invoke({"stock_code": code}))
            if valuation and "error" not in valuation:
                indicators.update(valuation)
        except Exception:
            pass
        if indicators:
            entry["indicators"] = indicators

        try:
            history = _parse_json_dict(get_stock_history.invoke({"stock_code": code}))
            if history and "error" not in history:
                entry["history"] = history
        except Exception:
            pass

        try:
            quote = _parse_json_dict(get_stock_quote.invoke({"stock_code": code}))
            if quote and "error" not in quote:
                entry["quote"] = quote
        except Exception:
            pass

        stock_data[code] = entry
    return stock_data
