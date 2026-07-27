"""百度千帆网页搜索工具：把行业/主题问题转换为结构化 A 股候选。"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

import requests

from finance_agent.config import (
    QIANFAN_API_KEY,
    QIANFAN_SEARCH_TIMEOUT,
    get_model_for_agent,
    safe_parse_json,
)


# 使用基础网页搜索接口，不再调用会产生模型费用的 ai_search/chat/completions。
_URL = "https://qianfan.baidubce.com/v2/ai_search/web_search"
_A_SHARE_CODE = re.compile(r"^(?:(?:60|68|00|30)\d{4}|[84]\d{5})$")


class QianfanSearchError(RuntimeError):
    """千帆搜索配置、请求或响应错误。"""


class QianfanStockSearch:
    def __init__(
        self,
        api_key: str = QIANFAN_API_KEY,
        model: str = "",
        timeout: int = QIANFAN_SEARCH_TIMEOUT,
    ):
        self.api_key = api_key
        # 为兼容旧调用保留 model 参数；基础搜索接口本身不使用模型。
        self.model = model
        self.timeout = timeout

    def _web_search(self, user_query: str, max_results: int) -> list[dict[str, str]]:
        query = (
            f"{user_query}。请搜索相关中国A股上市公司、证券简称、六位股票代码、"
            "主营业务和所属行业；优先使用交易所、上市公司和权威财经来源。"
        )
        payload = {
            "messages": [{"role": "user", "content": query}],
            "search_source": "baidu_search_v2",
            "resource_type_filter": [
                {"type": "web", "top_k": min(max(max_results * 2, 5), 10)}
            ],
            "search_recency_filter": "year",
        }
        try:
            response = requests.post(
                _URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout,
            )
            body = response.json()
            response.raise_for_status()
        except requests.RequestException as exc:
            detail = ""
            try:
                detail = response.text[:500]
            except UnboundLocalError:
                pass
            raise QianfanSearchError(f"千帆网页搜索请求失败: {exc}; {detail}") from exc
        except ValueError as exc:
            raise QianfanSearchError("千帆网页搜索返回了非 JSON 响应") from exc

        if body.get("code"):
            raise QianfanSearchError(
                f"千帆网页搜索返回错误 {body.get('code')}: {body.get('message', '')}"
            )

        references: list[dict[str, str]] = []
        for ref in body.get("references", []):
            if not isinstance(ref, dict):
                continue
            url = str(ref.get("url", "")).strip()
            content = str(ref.get("content", "")).strip()
            if not url or not content:
                continue
            references.append({
                "title": str(ref.get("title", "")).strip(),
                "url": url,
                "date": str(ref.get("date", "")).strip(),
                "content": content[:1200],
            })
        if not references:
            raise QianfanSearchError("千帆网页搜索未返回可用的搜索资料")
        return references

    @staticmethod
    def _structure_candidates(
        user_query: str,
        references: list[dict[str, str]],
        max_results: int,
    ) -> list[dict[str, Any]]:
        prompt = f"""你是证券资料提取器。请根据用户问题和搜索资料，提取最多 {max_results} 只直接相关的中国 A 股上市公司。

用户问题：{user_query}

搜索资料：
{json.dumps(references, ensure_ascii=False)}

仅输出合法 JSON，不要输出 Markdown。格式必须为：
{{"stocks":[{{"code":"六位股票代码","name":"证券简称","industry":"所属行业或主题","reason":"基于搜索资料的入选事实","source_urls":["资料中存在的URL"]}}]}}

要求：代码和证券简称必须匹配；不得包含港股、美股、基金；不得承诺收益；不得使用搜索资料之外的 URL；资料不足的公司不要输出。"""
        try:
            message = get_model_for_agent("data_fetch").invoke(prompt)
            content = getattr(message, "content", str(message))
            parsed = safe_parse_json(content, {})
            if isinstance(parsed, dict):
                stocks = parsed.get("stocks", [])
            elif isinstance(parsed, list):
                stocks = parsed
            else:
                stocks = []
        except Exception as exc:
            raise QianfanSearchError(f"搜索结果结构化失败: {exc}") from exc
        if not isinstance(stocks, list):
            raise QianfanSearchError("搜索结果结构化响应缺少 stocks 数组")
        return stocks

    @staticmethod
    def _extract_codes_from_references(
        references: list[dict[str, str]], max_results: int,
    ) -> list[dict[str, Any]]:
        """Fallback when model structuring fails: extract A-share codes from sources.

        Names are intentionally left empty and are populated by BaoStock's identity
        lookup before the candidates are used.
        """
        found: dict[str, dict[str, Any]] = {}
        for ref in references:
            text = f"{ref.get('title', '')}\n{ref.get('content', '')}"
            for code in re.findall(r"(?<!\d)((?:60|68|00|30)\d{4}|[84]\d{5})(?!\d)", text):
                if code not in found:
                    found[code] = {
                        "code": code,
                        "name": "",
                        "industry": "",
                        "reason": f"搜索资料中明确出现 A 股代码 {code}",
                        "source_urls": [ref["url"]],
                        "source": "baidu_qianfan_web_search_fallback",
                    }
                elif ref["url"] not in found[code]["source_urls"]:
                    found[code]["source_urls"].append(ref["url"])
                if len(found) >= max_results:
                    break
            if len(found) >= max_results:
                break
        return list(found.values())

    def search(self, user_query: str, max_results: int = 5) -> list[dict[str, Any]]:
        """联网检索并返回经过结构校验的 A 股候选列表。"""
        if not self.api_key:
            raise QianfanSearchError("未配置 QIANFAN_API_KEY")
        max_results = min(max(int(max_results), 1), 10)
        references = self._web_search(user_query, max_results)
        structure_error = ""
        try:
            stocks = self._structure_candidates(user_query, references, max_results)
        except QianfanSearchError as exc:
            structure_error = str(exc)
            stocks = []
        if not stocks:
            stocks = self._extract_codes_from_references(references, max_results)
        if not stocks and structure_error:
            raise QianfanSearchError(structure_error)

        reference_urls = {ref["url"] for ref in references}
        fallback_urls = [ref["url"] for ref in references[:2]]
        valid: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in stocks:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code", "")).strip()
            name = str(item.get("name", "")).strip()
            if not _A_SHARE_CODE.fullmatch(code) or code in seen:
                continue
            seen.add(code)
            item_urls = [
                str(url) for url in item.get("source_urls", [])
                if url and str(url) in reference_urls
            ]
            valid.append({
                "code": code,
                "name": name,
                "industry": str(item.get("industry", "")).strip(),
                "reason": str(item.get("reason", "")).strip(),
                "source_urls": item_urls or fallback_urls,
                "source": "baidu_qianfan_web_search",
            })
            if len(valid) >= max_results:
                break
        if not valid:
            raise QianfanSearchError("搜索资料中没有通过校验的 A 股候选")
        return valid

    def search_market_overview(self, user_query: str) -> str:
        """根据网页搜索资料直接回答板块、行业、概念等市场概览问题。"""
        if not self.api_key:
            raise QianfanSearchError("未配置 QIANFAN_API_KEY")
        references = self._web_search(user_query, max_results=8)
        prompt = f"""你是证券市场资料整理助手。当前日期是 {date.today().isoformat()}。

用户问题：{user_query}

网页搜索资料：
{json.dumps(references, ensure_ascii=False)}

请直接回答用户的问题。要求：
1. 严格依据资料，不得把个股涨幅冒充板块涨幅，不得编造排名或数值。
2. 正确解释“昨天”等相对日期；A股非交易日时，明确说明采用的最近交易日。
3. 若资料不足以确认完整排名，明确说明数据不足，并列出资料能确认的内容。
4. 使用简洁中文 Markdown；关键结论后标注来源链接，URL 只能取自搜索资料。
5. 结尾添加“公开市场资料可能存在口径差异，请以交易所或行情终端为准。”
"""
        try:
            message = get_model_for_agent("data_fetch").invoke(prompt)
            answer = str(getattr(message, "content", message)).strip()
        except Exception as exc:
            raise QianfanSearchError(f"市场搜索结果整理失败: {exc}") from exc
        if not answer:
            raise QianfanSearchError("市场搜索未生成有效回答")
        return answer

    def search_financial_fallback(
        self, stock_code: str, missing_fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """当 BaoStock 财务数据缺失时，用千帆搜索从网络获取兜底数据。

        Args:
            stock_code: A 股 6 位代码
            missing_fields: 缺失的字段名列表（如 ["roe","pe","pb"]），
                            为空则获取全部可用的基本面数据。

        Returns:
            包含财务指标的字典，source 标记为 "qianfan_fallback"。
            搜索失败时返回 {"error": "...", "source": "qianfan_fallback"}。
        """
        if not self.api_key:
            return {"error": "未配置 QIANFAN_API_KEY", "source": "qianfan_fallback", "code": stock_code}

        field_hints = {
            "roe": "ROE净资产收益率",
            "net_profit_margin": "净利率",
            "gross_margin": "毛利率",
            "revenue_growth": "营业收入增长率",
            "net_profit_growth": "净利润增长率",
            "total_asset_growth": "总资产增长率",
            "debt_ratio": "资产负债率",
            "current_ratio": "流动比率",
            "quick_ratio": "速动比率",
            "eps": "每股收益EPS",
            "net_profit": "净利润",
            "pe": "市盈率PE",
            "pb": "市净率PB",
            "name": "公司名称",
            "industry": "所属行业",
        }
        if missing_fields:
            targets = {f: field_hints.get(f, f) for f in missing_fields if f in field_hints}
        else:
            targets = dict(field_hints)
        target_desc = "、".join(targets.values())

        query = (
            f"A股股票代码{stock_code}的基本面财务数据：{target_desc}。"
            "请从东方财富、同花顺、新浪财经、雪球等来源搜索该股票最新披露的财务指标数值。"
        )
        try:
            references = self._web_search(query, max_results=5)
        except QianfanSearchError as exc:
            return {"error": f"千帆搜索失败: {exc}", "source": "qianfan_fallback", "code": stock_code}

        # Combine all reference content into a single text for extraction
        combined = "\n\n".join(
            f"[来源: {ref.get('title', '')}] {ref.get('content', '')}"
            for ref in references
        )

        # LLM extraction of financial values
        extract_prompt = f"""你是财务数据提取器。请从以下网页搜索资料中，提取A股股票 {stock_code} 的最新财务指标。

需要提取的字段：{target_desc}

搜索资料：
{combined[:8000]}

仅输出合法JSON，格式：
{{"name":"公司名称","industry":"所属行业","pe":市盈率数值,"pb":市净率数值,"roe":ROE百分比数值,"net_profit_margin":净利率百分比数值,"gross_margin":毛利率百分比数值,"revenue_growth":营收增长率百分比数值,"net_profit_growth":净利增长率百分比数值,"total_asset_growth":总资产增长率百分比数值,"debt_ratio":资产负债率百分比数值,"current_ratio":流动比率数值,"quick_ratio":速动比率数值,"eps":每股收益数值,"net_profit":净利润数值(元),"date":"数据所属报告期"}}

规则：
- 只提取搜索资料中明确出现的数值，不要编造
- 百分比类指标（ROE、净利率等）使用百分比数值（如ROE=15表示15%），不要使用小数
- PE/PB使用倍数值
- 无法提取的字段设为null
- 如果搜索资料中完全没有该股票的信息，返回空JSON {{}}"""

        try:
            message = get_model_for_agent("data_fetch").invoke(extract_prompt)
            content = getattr(message, "content", str(message))
            parsed = safe_parse_json(content, {})
        except Exception:
            parsed = {}

        if not isinstance(parsed, dict) or not parsed:
            return {"error": "千帆搜索未找到该股票的财务数据", "source": "qianfan_fallback", "code": stock_code}

        result: dict[str, Any] = {"code": stock_code, "source": "qianfan_fallback"}
        # Map extracted fields to the standard indicator schema
        value_keys = [
            "name", "industry", "pe", "pb", "roe", "net_profit_margin",
            "gross_margin", "revenue_growth", "net_profit_growth",
            "total_asset_growth", "debt_ratio", "current_ratio",
            "quick_ratio", "eps", "net_profit", "date",
        ]
        for key in value_keys:
            val = parsed.get(key)
            if val is not None:
                result[key] = val

        # Attach source references
        result["source_urls"] = [ref.get("url", "") for ref in references[:3]]
        return result
