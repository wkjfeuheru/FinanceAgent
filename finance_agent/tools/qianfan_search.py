"""百度千帆网页搜索工具：把行业/主题问题转换为结构化 A 股候选。"""

from __future__ import annotations

import json
import re
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
        stocks = self._structure_candidates(user_query, references, max_results)
        if not stocks:
            stocks = self._extract_codes_from_references(references, max_results)

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
