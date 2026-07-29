"""A股市场资料搜索工具：直接抓取东方财富/同花顺/新浪财经公开网页数据。

数据源策略：
1. 板块/行业市场概览 → 东方财富 push2 接口（主）+ 新浪财经（备）
2. 板块成份股候选搜索 → 东方财富板块成份股接口
3. 基本面指标 → 由 baostock 获取，本模块不负责基本面兜底

所有数据均来自公开网页接口的直接抓取，不依赖 LLM 联网搜索。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from finance_agent.data.market import (
    EastMoneyMarketData,
    MarketDataError,
    SinaMarketData,
    fetch_market_overview,
    fetch_sector_candidates,
)

logger = logging.getLogger(__name__)

_A_SHARE_CODE = re.compile(r"^(?:(?:60|68|00|30)\d{4}|[84]\d{5})$")


class WebSearchError(RuntimeError):
    """市场搜索配置、请求或响应错误。"""


class MarketSearch:
    """市场资料搜索工具，基于东方财富/新浪财经公开网页接口。

    对外方法签名：
    - search(): 行业/主题候选搜索（东方财富板块成份股）
    - search_market_overview(): 板块/行业市场概览（东方财富/新浪财经直接抓取）

    数据源：
    1. 东方财富 push2 接口（直接 JSON，主数据源）
    2. 新浪财经行业接口（备用数据源）
    """

    def __init__(self, timeout: int = 15):
        self._em_data = EastMoneyMarketData(timeout=timeout)
        self._sina_data = SinaMarketData(timeout=timeout)

    def search(self, user_query: str, max_results: int = 5) -> list[dict[str, Any]]:
        """搜索相关 A 股候选列表。

        通过东方财富板块成份股接口获取：根据用户问题匹配板块，返回该板块的成份股。
        若未匹配到具体板块，则返回领涨行业的成份股。
        """
        max_results = min(max(int(max_results), 1), 10)

        try:
            candidates = fetch_sector_candidates(
                user_query, max_results=max_results, em_data=self._em_data,
            )
        except MarketDataError as exc:
            raise WebSearchError(f"板块成份股搜索失败: {exc}") from exc

        if not candidates:
            raise WebSearchError("未匹配到相关板块或板块无成份股")

        valid: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in candidates:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code", "")).strip()
            if not _A_SHARE_CODE.fullmatch(code) or code in seen:
                continue
            seen.add(code)
            valid.append({
                "code": code,
                "name": str(item.get("name", "")).strip(),
                "industry": str(item.get("industry", "")).strip(),
                "reason": str(item.get("reason", "")).strip(),
                "source_urls": [],
                "source": "eastmoney_sector",
            })
            if len(valid) >= max_results:
                break

        if not valid:
            raise WebSearchError("板块成份股中没有通过校验的 A 股候选")
        return valid

    def search_market_overview(self, user_query: str) -> str:
        """回答板块、行业、概念等市场概览问题。

        直接抓取东方财富行业/概念板块排行，失败时降级到新浪财经。
        """
        try:
            return fetch_market_overview(
                user_query, em_data=self._em_data, sina_data=self._sina_data,
            )
        except MarketDataError as exc:
            raise WebSearchError(f"市场概览数据获取失败: {exc}") from exc
