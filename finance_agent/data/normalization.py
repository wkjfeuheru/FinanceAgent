"""统一各数据源返回的原始字段名与记录时间顺序。

适配器出口必须满足以下契约，工具层（``orchestrator.tools.stockdata``）与研究层
（``research.scoring``）据此直接读取字段，不再感知数据源差异：

1. 命中统一字段表的厂商字段被改写为统一英文名，未识别的厂商字段原样保留；
2. 日线/日估值/财务记录统一按时间**升序**排列，因此最后一行为最新记录；
3. 日期统一为 ISO ``YYYY-MM-DD`` 文本（兼容 ``datetime``、``date`` 与
   ``YYYYMMDD`` 三种来源格式）。

例如 AKShare 的 ``stock_zh_a_hist`` 返回中文列（``日期/开盘/收盘/...``），
BaoStock 返回 ``date/.../pctChg``，Tushare 返回 ``trade_date``（``YYYYMMDD``）。
若不在适配器出口统一，研究评分会因为读不到 ``close`` 而永远得到空评分。
"""

from __future__ import annotations

from datetime import date, datetime
from math import isnan
from re import fullmatch
from typing import Any

# 统一日线字段：trade_date/open/high/low/close/vol/amount/change/pct_chg。
DAILY_ALIASES: dict[str, tuple[str, ...]] = {
    "trade_date": ("trade_date", "date", "日期"),
    "open": ("open", "开盘"),
    "high": ("high", "最高"),
    "low": ("low", "最低"),
    "close": ("close", "收盘"),
    "vol": ("vol", "volume", "成交量"),
    "amount": ("amount", "成交额"),
    "change": ("change", "change_amount", "涨跌额"),
    "pct_chg": ("pct_chg", "pctChg", "change_pct", "涨跌幅"),
}

# 统一日估值字段：pe/pe_ttm/pe_lyr/pb/ps/ps_ttm/total_mv/circ_mv。
#
# PE 口径必须严格区分：``pe_ttm`` 是研究评分的唯一 PE 输入，``pe_lyr`` 承载静态
# PE 且不参与评分。因此 ``pe`` **不再以 ``pe_ttm`` 兜底**——否则同时返回两种口径
# 的数据源（东方财富 ``stock_value_em`` 的 ``PE(TTM)`` 与 ``PE(静)``）取到哪个是不
# 确定的。带括号的厂商标签保持由适配器显式映射，不进本表，避免模糊匹配再次把
# 两种口径混为一谈；``pe_ttm`` 仍保留 ``pe`` 作为"厂商原生 pe 即 TTM"的兜底。
VALUATION_ALIASES: dict[str, tuple[str, ...]] = {
    "trade_date": ("trade_date", "date", "日期", "数据日期"),
    "pe": ("pe", "市盈率"),
    "pe_ttm": ("pe_ttm", "pe", "市盈率ttm", "peTTM"),
    "pe_lyr": ("pe_lyr",),
    "pb": ("pb", "pb_mrq", "市净率", "pbMRQ"),
    "ps": ("ps", "ps_ttm", "市销率"),
    "ps_ttm": ("ps_ttm", "ps", "市销率", "psTTM"),
    "total_mv": ("total_mv", "total_market_cap", "总市值"),
    "circ_mv": ("circ_mv", "circ_market_cap", "流通市值"),
}

# 统一财务指标字段：end_date/ann_date/roe/or_yoy/netprofit_yoy。
FINANCIAL_ALIASES: dict[str, tuple[str, ...]] = {
    "end_date": ("end_date", "报告期", "日期"),
    "ann_date": ("ann_date", "公告日期"),
    "roe": ("roe", "roe_wa", "roe_dt", "roe_waa"),
    "or_yoy": ("or_yoy", "revenue_yoy"),
    "netprofit_yoy": ("netprofit_yoy", "profit_yoy"),
}

# 中文标签只做子串匹配，以兼容新浪源 ``净资产收益率(%)`` / ``加权净资产收益率(%)``
# 这类带前后缀的写法；匹配时优先选择无“加权/扣除”前缀的短标签。
FINANCIAL_LABEL_PATTERNS: dict[str, tuple[str, ...]] = {
    "roe": ("净资产收益率",),
    "or_yoy": ("主营业务收入增长率", "营业收入增长率"),
    "netprofit_yoy": ("净利润增长率",),
}

# 统一基础信息字段：ts_code/code/name/industry/list_date。
BASIC_ALIASES: dict[str, tuple[str, ...]] = {
    "ts_code": ("ts_code",),
    "code": ("code", "代码", "symbol"),
    "name": ("name", "名称", "code_name"),
    "industry": ("industry", "行业"),
    "list_date": ("list_date", "上市日期", "ipoDate"),
}

# 统一交易日历字段：cal_date/is_open。
TRADE_CAL_ALIASES: dict[str, tuple[str, ...]] = {
    "cal_date": ("cal_date", "calendar_date", "date", "日期"),
    "is_open": ("is_open", "is_trading_day", "交易状态"),
}

_LIST_KEYS = ("data", "items", "results", "list", "records")


def _is_missing(value: Any) -> bool:
    """判断字段是否视为缺失（None、空串、NaN）。"""
    if value is None or value == "":
        return True
    if isinstance(value, float):
        return isnan(value)
    return False


def _iso_date(value: Any) -> Any:
    """把 ``datetime``/``date``/``YYYYMMDD`` 统一为 ``YYYY-MM-DD`` 文本。"""
    if isinstance(value, (datetime, date)):
        return value.isoformat()[:10]
    text = str(value).strip()
    if fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text or None


def _unify(record: dict[str, Any], aliases: dict[str, tuple[str, ...]]) -> dict[str, Any]:
    """把命中的厂商字段改写为统一字段名，并移除被消费的别名键。"""
    unified = dict(record)
    canonical = set(aliases)
    consumed: set[str] = set()
    for target, sources in aliases.items():
        source = next(
            (name for name in sources if not _is_missing(record.get(name))),
            None,
        )
        if source is None:
            continue
        unified[target] = record[source]
        if source != target and source not in canonical:
            consumed.add(source)
    for name in consumed:
        unified.pop(name, None)
    return unified


def _best_label(record: dict[str, Any], needles: tuple[str, ...]) -> str | None:
    """按子串命中中文标签，优先返回无“加权/扣除”前缀的最短标签。"""
    candidates = [
        key for key in record
        if any(needle in key for needle in needles) and not _is_missing(record.get(key))
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda key: ("加权" in key or "扣除" in key, len(key)))


def _apply_label_patterns(
    unified: dict[str, Any],
    patterns: dict[str, tuple[str, ...]],
) -> dict[str, Any]:
    """用中文标签子串补齐精确别名未命中的财务字段。"""
    canonical = set(unified)
    for target, needles in patterns.items():
        if not _is_missing(unified.get(target)):
            continue
        source = _best_label(unified, needles)
        if source is None:
            continue
        unified[target] = unified[source]
        if source != target and source not in canonical:
            unified.pop(source, None)
    return unified


def _sorted_ascending(records: list[Any], date_key: str) -> list[Any]:
    """按日期升序排序；无日期的记录保持原相对顺序并排在最后。"""
    keyed: list[tuple[bool, str, int, Any]] = []
    for index, record in enumerate(records):
        raw = record.get(date_key) if isinstance(record, dict) else None
        text = _iso_date(raw) if not _is_missing(raw) else None
        keyed.append((text is None, text or "", index, record))
    if all(item[0] for item in keyed):
        return records
    return [item[3] for item in sorted(keyed, key=lambda item: item[:3])]


def _normalize(
    payload: Any,
    aliases: dict[str, tuple[str, ...]],
    *,
    date_key: str = "",
    patterns: dict[str, tuple[str, ...]] | None = None,
) -> Any:
    """规范化单个记录、记录列表或 ``{"data": [...]}`` 包装结果。"""
    if isinstance(payload, list):
        return _normalize_list(payload, aliases, date_key, patterns)
    if isinstance(payload, dict):
        for key in _LIST_KEYS:
            value = payload.get(key)
            if isinstance(value, list):
                result = dict(payload)
                result[key] = _normalize_list(value, aliases, date_key, patterns)
                return result
        return _normalize_record(payload, aliases, date_key, patterns)
    return payload


def _normalize_list(
    rows: list[Any],
    aliases: dict[str, tuple[str, ...]],
    date_key: str,
    patterns: dict[str, tuple[str, ...]] | None,
) -> list[Any]:
    """规范化列表中的每条记录，并保证时间升序。"""
    normalized = [
        _normalize_record(row, aliases, date_key, patterns)
        if isinstance(row, dict) else row
        for row in rows
    ]
    if not date_key:
        return normalized
    return _sorted_ascending(normalized, date_key)


def _normalize_record(
    record: dict[str, Any],
    aliases: dict[str, tuple[str, ...]],
    date_key: str,
    patterns: dict[str, tuple[str, ...]] | None,
) -> dict[str, Any]:
    """规范化单条记录：统一字段名、补齐中文标签、校准日期格式。"""
    unified = _unify(record, aliases)
    if patterns:
        unified = _apply_label_patterns(unified, patterns)
    if date_key and not _is_missing(unified.get(date_key)):
        unified[date_key] = _iso_date(unified[date_key])
    return unified


def normalize_daily_records(payload: Any) -> Any:
    """统一日线记录（trade_date/open/high/low/close/vol/amount/change/pct_chg）。"""
    return _normalize(payload, DAILY_ALIASES, date_key="trade_date")


def normalize_valuation_records(payload: Any) -> Any:
    """统一日估值记录（pe/pe_ttm/pb/ps/total_mv/circ_mv）。"""
    return _normalize(payload, VALUATION_ALIASES, date_key="trade_date")


def normalize_financial_records(payload: Any) -> Any:
    """统一财务指标记录（end_date/ann_date/roe/or_yoy/netprofit_yoy）。"""
    return _normalize(
        payload, FINANCIAL_ALIASES, date_key="end_date",
        patterns=FINANCIAL_LABEL_PATTERNS,
    )


def normalize_basic_records(payload: Any) -> Any:
    """统一基础信息记录（ts_code/code/name/industry/list_date）。"""
    return _normalize(payload, BASIC_ALIASES)


def normalize_trade_cal_records(payload: Any) -> Any:
    """统一交易日历记录（cal_date/is_open），日期统一为 ISO 文本。"""
    return _normalize(payload, TRADE_CAL_ALIASES, date_key="cal_date")


__all__ = [
    "BASIC_ALIASES",
    "DAILY_ALIASES",
    "FINANCIAL_ALIASES",
    "FINANCIAL_LABEL_PATTERNS",
    "TRADE_CAL_ALIASES",
    "VALUATION_ALIASES",
    "normalize_basic_records",
    "normalize_daily_records",
    "normalize_financial_records",
    "normalize_trade_cal_records",
    "normalize_valuation_records",
]
