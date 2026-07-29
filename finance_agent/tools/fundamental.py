"""BaoStock 股票数据获取工具。

封装为 LangChain tool，供金融数据获取 Agent 调用。
"""

from __future__ import annotations

import json

from langchain_core.tools import tool

from finance_agent.data.baostock import get_datasource


def _json(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


@tool
def get_stock_realtime_quote(stock_code: str) -> str:
    """获取A股实时行情数据。

    Args:
        stock_code: 股票代码
    Returns:
        JSON 字符串，包含最新价、涨跌幅、成交量、市盈率等
    """
    data = get_datasource().get_realtime_quote(stock_code)
    return _json(data)


@tool
def get_stock_history(
    stock_code: str,
    period: str = "daily",
    start_date: str = "",
    end_date: str = "",
) -> str:
    """获取A股历史K线数据，用于计算收益率和波动率。

    Args:
        stock_code: 股票代码，如 600519
        period: K线周期 daily/weekly/monthly，默认 daily
        start_date: 开始日期 YYYY-MM-DD，默认最近一年
        end_date: 结束日期 YYYY-MM-DD，默认今天

    Returns:
        JSON 字符串，包含日期、开盘、收盘、最高、最低、成交量等
    """
    result = get_datasource().get_history(stock_code, period, start_date, end_date)
    # get_history 失败时返回 dict 错误（而非 DataFrame）
    if isinstance(result, dict):
        return _json(result)
    df = result
    if df.empty:
        return _json({"error": f"未获取到 {stock_code} 的历史数据", "code": stock_code})
    # 转为可序列化格式，只取关键字段
    records = df[["date", "open", "close", "high", "low", "volume", "change_pct"]].copy()
    records["date"] = records["date"].astype(str)
    result = {
        "code": stock_code,
        "count": len(records),
        "data": records.to_dict(orient="records"),
    }
    return _json(result)


@tool
def get_financial_indicators(stock_code: str) -> str:
    """获取A股财务分析指标，用于基本面分析。

    Args:
        stock_code: 股票代码
    Returns:
        JSON 字符串，包含 PE/PB/ROE/净利率/营收增长率/负债率等
    """
    data = get_datasource().get_financial_indicators(stock_code)
    return _json(data)


@tool
def get_stock_basic_info(stock_code: str) -> str:
    """获取A股基本信息，包括公司名称、行业、市值等。

    Args:
        stock_code: 股票代码
    Returns:
        JSON 字符串，包含公司名称、行业、上市时间、市值等
    """
    data = get_datasource().get_basic_info(stock_code)
    return _json(data)
