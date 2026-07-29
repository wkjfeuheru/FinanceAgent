"""A股板块与行业市场数据直接抓取模块。

数据来源（均为公开网页接口，直接抓取）：
- 东方财富行情中心 push2 接口：行业板块/概念板块排行、板块成份股
- 同花顺行业板块页面：板块列表与涨跌幅
- 新浪财经行业板块接口：行业涨跌概览

设计原则：
1. 东方财富为主数据源（JSON 接口，结构稳定）
2. 新浪财经为备用数据源（覆盖行业涨跌）
3. 所有请求绕过代理，直连国内数据源
4. 基本面指标仍由 baostock 获取，本模块仅负责板块/行业市场资料
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date, timedelta
from typing import Any

import requests

logger = logging.getLogger(__name__)

# 国内数据源必须绕过代理，否则会导致超时或返回境外节点内容
_DOMESTIC_HOSTS = "eastmoney.com, push2.eastmoney.com, 10jqka.com.cn, sina.com.cn, finance.sina.com.cn, vip.stock.finance.sina.com.cn"
_existing_no_proxy = os.environ.get("NO_PROXY", "")
if _existing_no_proxy:
    os.environ["NO_PROXY"] = f"{_existing_no_proxy}, {_DOMESTIC_HOSTS}"
else:
    os.environ["NO_PROXY"] = _DOMESTIC_HOSTS
_existing_http_proxy = os.environ.get("HTTP_PROXY", "") or os.environ.get("http_proxy", "")
os.environ.setdefault("NO_PROXY", _DOMESTIC_HOSTS)

# 东方财富 push2 接口（返回 JSON）
# pz=200 扩大板块搜索范围（行业/概念板块总数约 ~100-200）
_EM_INDUSTRY_RANK_URL = (
    "https://push2.eastmoney.com/api/qt/clist/get"
    "?pn=1&pz=200&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:90+t:2"
    "&fields=f12,f14,f3,f2,f4,f8,f104,f105"
)
_EM_CONCEPT_RANK_URL = (
    "https://push2.eastmoney.com/api/qt/clist/get"
    "?pn=1&pz=200&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:90+t:3"
    "&fields=f12,f14,f3,f2,f4,f8,f104,f105"
)
_EM_SECTOR_STOCKS_URL = (
    "https://push2.eastmoney.com/api/qt/clist/get"
    "?pn=1&pz=100&po=1&np=1&fltt=2&invt=2&fid=f3&fs=b:{sector_code}"
    "&fields=f12,f14,f3,f2,f4,f8,f15,f16,f17,f18,f6"
)

# 新浪财经行业板块接口
_SINA_INDUSTRY_URL = "http://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php"

_DEFAULT_TIMEOUT = 15
_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://quote.eastmoney.com/",
}

# A股代码正则：沪市60/68、深市00/30、北交所83/87/92
_A_SHARE_CODE = re.compile(r"^(?:(?:60|68|00|30)\d{4}|[48]\d{5}|9[2-9]\d{4})$")


def _get_last_trading_day(today: date | None = None) -> date:
    """返回最近一个 A 股交易日（仅跳过周末，不判断节假日）。"""
    d = today or date.today()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


class MarketDataError(RuntimeError):
    """板块/行业市场数据抓取错误。"""


class EastMoneyMarketData:
    """东方财富行情中心公开接口封装。

    提供板块/行业市场资料的直接抓取，不依赖 LLM 联网搜索：
    - get_industry_ranking(): 行业板块涨跌排行
    - get_concept_ranking(): 概念板块涨跌排行
    - get_sector_stocks(): 指定板块的成份股列表
    - get_top_industries(): 涨幅/跌幅领涨行业
    """

    def __init__(self, timeout: int = _DEFAULT_TIMEOUT):
        self.timeout = timeout

    def _fetch_json(self, url: str) -> dict[str, Any]:
        """请求东方财富 JSON 接口，返回解析后的 dict。"""
        try:
            resp = requests.get(
                url, headers=_DEFAULT_HEADERS, timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            raise MarketDataError(f"东方财富接口请求失败: {exc}") from exc
        except ValueError as exc:
            raise MarketDataError(f"东方财富接口响应非 JSON: {exc}") from exc

        if not isinstance(data, dict):
            raise MarketDataError("东方财富接口响应格式异常")
        if data.get("rc") != 0:
            raise MarketDataError(
                f"东方财富接口返回错误: {data.get('rt', '')} {data.get('svrmsg', '')}"
            )
        return data

    @staticmethod
    def _parse_rank_list(data: dict[str, Any]) -> list[dict[str, Any]]:
        """解析东方财富板块排行 JSON，返回标准化板块列表。"""
        diff = data.get("data", {}) or {}
        items = diff.get("diff", []) or []
        result: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            code = str(item.get("f12", "")).strip()
            name = str(item.get("f14", "")).strip()
            change_pct = item.get("f3")
            price = item.get("f2")
            change_amount = item.get("f4")
            turnover = item.get("f8")
            up_count = item.get("f104")
            down_count = item.get("f105")
            result.append({
                "code": code,
                "name": name,
                "change_pct": _safe_float(change_pct),
                "price": _safe_float(price),
                "change_amount": _safe_float(change_amount),
                "turnover_rate": _safe_float(turnover),
                "up_count": int(up_count) if up_count and str(up_count) != "-" else 0,
                "down_count": int(down_count) if down_count and str(down_count) != "-" else 0,
                "source": "eastmoney",
            })
        return result

    def get_industry_ranking(self) -> list[dict[str, Any]]:
        """获取行业板块涨跌排行（按涨幅降序）。"""
        data = self._fetch_json(_EM_INDUSTRY_RANK_URL)
        return self._parse_rank_list(data)

    def get_concept_ranking(self) -> list[dict[str, Any]]:
        """获取概念板块涨跌排行（按涨幅降序）。"""
        data = self._fetch_json(_EM_CONCEPT_RANK_URL)
        return self._parse_rank_list(data)

    def get_sector_stocks(
        self, sector_code: str, max_results: int = 50,
    ) -> list[dict[str, Any]]:
        """获取指定板块的成份股列表。

        Args:
            sector_code: 东方财富板块代码，如 BK0475（半导体）
            max_results: 最多返回的股票数量

        Returns:
            标准化股票列表，含 code/name/change_pct/price 等
        """
        url = _EM_SECTOR_STOCKS_URL.format(sector_code=sector_code)
        data = self._fetch_json(url)
        diff = data.get("data", {}) or {}
        items = diff.get("diff", []) or []
        result: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            code = str(item.get("f12", "")).strip()
            if not _A_SHARE_CODE.fullmatch(code):
                continue
            name = str(item.get("f14", "")).strip()
            result.append({
                "code": code,
                "name": name,
                "change_pct": _safe_float(item.get("f3")),
                "price": _safe_float(item.get("f2")),
                "change_amount": _safe_float(item.get("f4")),
                "turnover_rate": _safe_float(item.get("f8")),
                "high": _safe_float(item.get("f15")),
                "low": _safe_float(item.get("f16")),
                "open": _safe_float(item.get("f17")),
                "prev_close": _safe_float(item.get("f18")),
                "amount": _safe_float(item.get("f6")),
                "source": "eastmoney",
            })
            if len(result) >= max_results:
                break
        return result

    def get_top_industries(
        self, top_n: int = 5, descending: bool = True,
    ) -> list[dict[str, Any]]:
        """获取涨幅（或跌幅）前 N 的行业板块。

        Args:
            top_n: 返回数量
            descending: True=涨幅最大，False=跌幅最大
        """
        ranking = self.get_industry_ranking()
        valid = [r for r in ranking if r.get("change_pct") is not None]
        valid.sort(key=lambda x: x["change_pct"], reverse=descending)
        return valid[:top_n]

    def get_top_concepts(
        self, top_n: int = 5, descending: bool = True,
    ) -> list[dict[str, Any]]:
        """获取涨幅（或跌幅）前 N 的概念板块。"""
        ranking = self.get_concept_ranking()
        valid = [r for r in ranking if r.get("change_pct") is not None]
        valid.sort(key=lambda x: x["change_pct"], reverse=descending)
        return valid[:top_n]

    def find_sector_by_keyword(self, keyword: str) -> dict[str, Any] | None:
        """根据关键词查找匹配的行业/概念板块。

        搜索策略：
        1. 先在缓存的行业/概念排行中搜索
        2. 若未找到，使用分页搜索全部板块
        3. 优先精确匹配，再做宽松匹配
        """
        if not keyword:
            return None
        kw = keyword.strip()

        # 策略1：在当前排行中搜索（快速路径）
        try:
            industries = self.get_industry_ranking()
        except MarketDataError:
            industries = []
        for ind in industries:
            if kw == ind.get("name", ""):
                return self._build_sector_result(ind, "industry")
        for ind in industries:
            if kw in ind.get("name", ""):
                return self._build_sector_result(ind, "industry")

        try:
            concepts = self.get_concept_ranking()
        except MarketDataError:
            concepts = []
        for con in concepts:
            if kw == con.get("name", ""):
                return self._build_sector_result(con, "concept")
        for con in concepts:
            if kw in con.get("name", ""):
                return self._build_sector_result(con, "concept")

        # 策略2：分页搜索全部板块（慢速但更全面）
        return self._search_sector_paginated(kw)

    @staticmethod
    def _build_sector_result(
        sector: dict[str, Any], sector_type: str,
    ) -> dict[str, Any]:
        return {
            "type": sector_type,
            "code": sector["code"],
            "name": sector["name"],
            "change_pct": sector.get("change_pct", 0),
        }

    def _search_sector_paginated(self, keyword: str) -> dict[str, Any] | None:
        """分页搜索全部行业/概念板块（最多5页，每页200条）。"""
        for sector_type, base_url in [
            ("industry", _EM_INDUSTRY_RANK_URL),
            ("concept", _EM_CONCEPT_RANK_URL),
        ]:
            for page in range(1, 6):
                url = base_url.replace("pn=1", f"pn={page}")
                try:
                    data = self._fetch_json(url)
                except MarketDataError:
                    break
                diff = data.get("data", {}) or {}
                items = diff.get("diff", []) or []
                if not items:
                    break
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("f14", "")).strip()
                    if name and keyword in name:
                        return {
                            "type": sector_type,
                            "code": str(item.get("f12", "")).strip(),
                            "name": name,
                            "change_pct": _safe_float(item.get("f3")),
                        }
                # 如果本页数量少于200，说明没有更多页
                if len(items) < 200:
                    break
        return None


class SinaMarketData:
    """新浪财经行业板块数据（备用数据源）。

    新浪财经的行业板块接口返回的是 JSONP/文本格式，需要解析。
    仅作为东方财富失败时的降级方案。
    """

    def __init__(self, timeout: int = _DEFAULT_TIMEOUT):
        self.timeout = timeout

    def get_industry_ranking(self) -> list[dict[str, Any]]:
        """获取新浪财经行业板块涨跌排行。"""
        try:
            resp = requests.get(
                _SINA_INDUSTRY_URL,
                headers={**_DEFAULT_HEADERS, "Referer": "http://finance.sina.com.cn/"},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            text = resp.text
        except requests.RequestException as exc:
            raise MarketDataError(f"新浪财经行业接口请求失败: {exc}") from exc

        # 新浪返回格式：var S_Finance_bankuai_sinaindustry = [["板块名","code","涨跌幅",...], ...]
        match = re.search(r"=\s*(\[.+\])\s*;?\s*$", text, re.DOTALL)
        if not match:
            raise MarketDataError("新浪财经行业接口响应格式无法解析")
        try:
            import json as _json
            raw_list = _json.loads(match.group(1))
        except ValueError as exc:
            raise MarketDataError(f"新浪财经行业接口 JSON 解析失败: {exc}") from exc

        result: list[dict[str, Any]] = []
        if not isinstance(raw_list, list):
            return result
        for item in raw_list:
            if not isinstance(item, list) or len(item) < 3:
                continue
            name = str(item[0]).strip()
            code = str(item[1]).strip()
            change_str = str(item[2]).strip().rstrip("%")
            try:
                change_pct = float(change_str)
            except ValueError:
                change_pct = 0.0
            result.append({
                "code": code,
                "name": name,
                "change_pct": change_pct,
                "price": 0.0,
                "change_amount": 0.0,
                "turnover_rate": 0.0,
                "up_count": 0,
                "down_count": 0,
                "source": "sina",
            })
        result.sort(key=lambda x: x["change_pct"], reverse=True)
        return result


def _safe_float(value: Any) -> float | None:
    """将东方财富返回的数值字段转为 float，处理 '-' 等占位符。"""
    if value is None or value == "" or value == "-":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# 用户提问关键词 → 展示模式映射
# 若命中跌幅关键词，则展示跌幅板块；否则默认只展示涨幅
_DECLINE_KEYWORDS = [
    "跌幅", "跌", "下跌", "领跌", "跌幅榜", "跌榜",
    "最差", "最惨", "跌幅前", "跌幅排行",
    "decline", "down", "drop", "fall",
]


def _user_wants_decline(user_query: str) -> bool:
    """判断用户是否询问跌幅相关内容。"""
    if not user_query:
        return False
    query_lower = user_query.lower()
    return any(kw in user_query or kw in query_lower for kw in _DECLINE_KEYWORDS)


def format_market_overview(
    user_query: str,
    industry_ranking: list[dict[str, Any]] | None = None,
    concept_ranking: list[dict[str, Any]] | None = None,
    last_trading_day: date | None = None,
) -> str:
    """根据抓取到的板块排行数据，生成结构化的市场概览文本。

    根据用户提问自动判断展示模式：
    - 询问跌幅相关 → 展示跌幅板块
    - 其他（含涨幅、大盘、板块等）→ 展示涨幅板块

    Args:
        user_query: 用户原始问题
        industry_ranking: 行业板块排行（已按涨幅降序）
        concept_ranking: 概念板块排行（已按涨幅降序）
        last_trading_day: 最近交易日

    Returns:
        Markdown 格式的市场概览文本
    """
    trading_day = last_trading_day or _get_last_trading_day()
    show_decline = _user_wants_decline(user_query)

    parts: list[str] = [
        f"## 市场板块概览（数据日期：{trading_day}）",
        "",
        f"数据来源：东方财富行情中心（截至 {trading_day} 收盘）",
        "",
    ]

    if industry_ranking:
        if show_decline:
            ranked = sorted(industry_ranking, key=lambda x: x.get("change_pct", 0))[:5]
            label = "行业板块跌幅前 5"
        else:
            ranked = industry_ranking[:5]
            label = "行业板块涨幅前 5"

        parts.append(f"### {label}")
        for ind in ranked:
            parts.append(
                f"- **{ind['name']}**（{ind['code']}）："
                f"涨跌幅 {ind.get('change_pct', 0):+.2f}%，"
                f"上涨 {ind.get('up_count', 0)} 家，下跌 {ind.get('down_count', 0)} 家"
            )
        parts.append("")
    else:
        parts.append("### 行业板块")
        parts.append("暂未获取到行业板块数据。")
        parts.append("")

    if concept_ranking:
        if show_decline:
            ranked = sorted(concept_ranking, key=lambda x: x.get("change_pct", 0))[:5]
            label = "概念板块跌幅前 5"
        else:
            ranked = concept_ranking[:5]
            label = "概念板块涨幅前 5"

        parts.append(f"### {label}")
        for con in ranked:
            parts.append(
                f"- **{con['name']}**（{con['code']}）："
                f"涨跌幅 {con.get('change_pct', 0):+.2f}%"
            )
        parts.append("")

    parts.append("> 公开市场资料可能存在口径差异，请以交易所或行情终端为准。")
    return "\n".join(parts)


def fetch_market_overview(
    user_query: str,
    em_data: EastMoneyMarketData | None = None,
    sina_data: SinaMarketData | None = None,
) -> str:
    """直接抓取板块/行业市场概览数据并格式化回复。

    优先使用东方财富，失败时降级到新浪财经。

    Args:
        user_query: 用户原始问题（用于判断查询范围）

    Returns:
        Markdown 格式的市场概览文本
    """
    em = em_data or EastMoneyMarketData()
    sina = sina_data or SinaMarketData()
    last_trading_day = _get_last_trading_day()

    industry_ranking: list[dict[str, Any]] = []
    concept_ranking: list[dict[str, Any]] = []

    # 主数据源：东方财富
    try:
        industry_ranking = em.get_industry_ranking()
    except MarketDataError as exc:
        logger.warning("东方财富行业板块接口失败，降级到新浪财经: %s", exc)
        try:
            industry_ranking = sina.get_industry_ranking()
        except MarketDataError as exc2:
            logger.error("新浪财经行业板块接口也失败: %s", exc2)

    try:
        concept_ranking = em.get_concept_ranking()
    except MarketDataError as exc:
        logger.warning("东方财富概念板块接口失败: %s", exc)

    if not industry_ranking and not concept_ranking:
        raise MarketDataError("所有数据源均无法获取板块行情数据")

    return format_market_overview(
        user_query, industry_ranking, concept_ranking, last_trading_day,
    )


def fetch_sector_candidates(
    user_query: str,
    max_results: int = 5,
    em_data: EastMoneyMarketData | None = None,
) -> list[dict[str, Any]]:
    """根据用户问题匹配板块，并返回该板块的成份股作为候选。

    流程：
    1. 从用户问题中提取板块/行业关键词
    2. 调用东方财富接口查找匹配的板块代码
    3. 获取该板块的成份股列表
    4. 按涨幅排序，返回前 N 只

    Args:
        user_query: 用户问题，如 "半导体行业有哪些值得关注的股票"
        max_results: 最多返回的候选股票数

    Returns:
        标准化候选股票列表
    """
    em = em_data or EastMoneyMarketData()

    # 从用户问题中提取板块关键词
    keyword = _extract_sector_keyword(user_query)
    if not keyword:
        # 未提取到具体板块关键词时，返回领涨行业的成份股
        try:
            top_industries = em.get_top_industries(top_n=1, descending=True)
            if top_industries:
                ind = top_industries[0]
                stocks = em.get_sector_stocks(ind["code"], max_results)
                return _normalize_candidates(stocks, ind)
        except MarketDataError as exc:
            raise MarketDataError(f"获取领涨行业成份股失败: {exc}") from exc
        return []

    sector = _try_match_sector(em, keyword)
    if not sector:
        raise MarketDataError(f"未找到匹配「{keyword}」的行业/概念板块")

    stocks = em.get_sector_stocks(sector["code"], max_results)
    if not stocks:
        raise MarketDataError(f"板块「{sector['name']}」没有可用的成份股")

    return _normalize_candidates(stocks, sector)


def _extract_sector_keyword(user_query: str) -> str:
    """从用户问题中提取板块/行业关键词。

    策略：
    1. 按长度从长到短排序噪声短语，确保多字词先于单字匹配
    2. 单字助词（的、了等）单独处理
    3. 最终兜底：若提取结果无意义，返回空由调用方回退
    """
    if not user_query:
        return ""

    # 按长度从长到短排列，确保多字词先匹配
    noise_phrases = sorted([
        # 动作/请求词（最长优先）
        "帮我推荐", "给我推荐", "请推荐", "推荐一下", "能推荐", "可以推荐",
        "帮我找一下", "帮我选一下", "给我讲讲",
        "帮我找", "帮我选",
        "请问一下", "请问下",
        # 行业/市场通用词
        "值得关注", "值得投资", "投资机会",
        "值得", "关注", "投资", "板块", "行业", "概念", "主题",
        "标的", "公司", "上市", "龙头", "领涨",
        # 疑问/修饰词
        "有哪些", "有什么", "什么", "哪些", "有没有",
        "几个", "多少", "一些", "一点",
        # 通用动词/修饰词
        "推荐", "讲讲", "一下",
        # 数量/单位
        "股票", "个股",
        # 标点
        "?", "？", "。", ".", "，", ",", "、",
    ], key=len, reverse=True)

    # 助词单独处理（这些字极少出现在行业名称中）
    aux_chars = "的了吗呢啊是和与及或"

    text = user_query
    for phrase in noise_phrases:
        text = text.replace(phrase, "")
    for ch in aux_chars:
        text = text.replace(ch, "")
    # 清理空白
    text = " ".join(text.split())
    text = text.strip()
    # 若剩余文本过长，可能是完整句子而非关键词
    if len(text) > 10:
        return ""
    return text


def _try_match_sector(
    em_data: "EastMoneyMarketData",
    keyword: str,
) -> dict[str, Any] | None:
    """尝试用关键词匹配板块，支持渐进式回退。

    匹配策略：
    1. 直接用完整关键词匹配（优先精确匹配）
    2. 逐步从头部移除字符，但至少保留2个字符
    3. 提取英文/缩写部分单独匹配
    4. 验证匹配质量：匹配到的板块名称必须包含关键词的核心部分
    """
    if not keyword:
        return None

    # 策略1：完整关键词匹配
    result = em_data.find_sector_by_keyword(keyword)
    if result:
        return result

    # 策略2：渐进式从头部移除字符（至少保留2个字符）
    for i in range(1, len(keyword) - 1):
        sub = keyword[i:]
        if len(sub) < 2:
            break
        result = em_data.find_sector_by_keyword(sub)
        if result and _is_quality_match(keyword, sub, result["name"]):
            return result

    # 策略3：提取英文/缩写部分（如 "AI"、"CPU"、"GPU"）
    import re
    english_parts = re.findall(r"[a-zA-Z]{2,}", keyword)
    for part in english_parts:
        result = em_data.find_sector_by_keyword(part)
        if result:
            return result

    return None


def _is_quality_match(
    original_keyword: str,
    matched_keyword: str,
    sector_name: str,
) -> bool:
    """验证匹配质量：确保匹配结果与原始关键词有实质关联。

    规则：
    - 板块名称必须包含匹配关键词
    - 匹配关键词至少是原始关键词的核心部分（长度不短于原始的60%）
    """
    if matched_keyword not in sector_name:
        return False
    # 匹配关键词长度不应太短，避免单字误匹配
    min_len = max(2, len(original_keyword) * 0.6)
    if len(matched_keyword) < min_len:
        return False
    return True


def _normalize_candidates(
    stocks: list[dict[str, Any]],
    sector: dict[str, Any],
) -> list[dict[str, Any]]:
    """将东方财富成份股列表标准化为候选股票格式。"""
    sector_name = sector.get("name", "")
    sector_type = sector.get("type", "industry")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for stock in stocks:
        code = stock.get("code", "")
        if not code or code in seen:
            continue
        seen.add(code)
        change_pct = stock.get("change_pct")
        reason = (
            f"属于{sector_type}板块「{sector_name}」成份股"
            + (f"，今日涨跌幅 {change_pct:+.2f}%" if change_pct is not None else "")
        )
        result.append({
            "code": code,
            "name": stock.get("name", ""),
            "industry": sector_name,
            "reason": reason,
            "source_urls": [],
            "source": "eastmoney_sector",
            "change_pct": change_pct,
            "price": stock.get("price"),
        })
    return result
