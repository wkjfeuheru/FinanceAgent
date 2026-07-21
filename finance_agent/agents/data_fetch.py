"""金融数据获取 Agent。

职责：根据用户输入的股票代码和期限从 BaoStock 获取金融数据
- 实时行情
- 历史K线数据
- 财务分析指标
- 股票基本信息

数据写入共享内存供下游Agent使用。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from finance_agent.agents.base import BaseFinanceAgent
from finance_agent.config import get_model_for_agent, safe_parse_json
from finance_agent.tools.stock_data import (
    get_stock_basic_info,
    get_financial_indicators,
    get_stock_history,
    get_stock_realtime_quote,
)


_DATA_FETCH_PROMPT = """你是金融数据获取专家。

## 身份
你负责从 BaoStock 获取A股金融数据，包括最近交易日行情、历史K线、财务指标和基本信息。

## 工作流程
1. 从共享上下文中读取用户画像（stock_codes、holding_period）
2. 对每只股票依次获取：基本信息 → 实时行情 → 财务指标 → 历史K线
3. 数据自动发布到共享内存供下游Agent使用

## 工具
- get_stock_basic_info: 股票基本信息（名称、行业、市值）
- get_stock_realtime_quote: 实时行情（最新价、涨跌幅）
- get_financial_indicators: 财务指标（PE/PB/ROE等）
- get_stock_history: 历史K线数据（用于计算收益率/波动率）

## 规则
- 股票代码为6位数字：60xxxx(沪市主板)/00xxxx(深市主板)/30xxxx(创业板)/68xxxx(科创板)
- 历史数据默认取最近一年
- 数据获取失败时说明原因，不要编造数据
- 所有数据都已写入共享内存，下游Agent可直接引用"""


_RESOLVE_STOCKS_PROMPT = """你是A股股票识别专家。

## 职责
从用户输入中识别股票名称（包括中文全称、简称、6位代码），返回对应的A股6位代码、名称、所属行业。

## 识别规则
- 用户可能输入中文全称（如"贵州茅台"）、简称（如"茅台"、"招行"）、或6位代码（如"600519"）
- 你必须基于自身知识将名称映射为6位A股代码
- 代码格式：60xxxx(沪市主板)/00xxxx(深市主板)/30xxxx(创业板)/68xxxx(科创板)
- 如果不确定某名称对应的代码，不要编造，跳过该股票

## 输出格式
返回JSON数组：
[
  {{"code": "600519", "name": "贵州茅台", "industry": "白酒"}},
  {{"code": "600036", "name": "招商银行", "industry": "银行"}}
]

如果未识别到任何股票，返回空数组 []。"""


KNOWN_A_SHARES: dict[str, dict[str, str]] = {
    "贵州茅台": {"code": "600519", "name": "贵州茅台", "industry": "白酒"},
    "茅台": {"code": "600519", "name": "贵州茅台", "industry": "白酒"},
    "浦发银行": {"code": "600000", "name": "浦发银行", "industry": "银行"},
    "招商银行": {"code": "600036", "name": "招商银行", "industry": "银行"},
    "招行": {"code": "600036", "name": "招商银行", "industry": "银行"},
    "中国平安": {"code": "601318", "name": "中国平安", "industry": "保险"},
    "平安银行": {"code": "000001", "name": "平安银行", "industry": "银行"},
    "五粮液": {"code": "000858", "name": "五粮液", "industry": "白酒"},
    "宁德时代": {"code": "300750", "name": "宁德时代", "industry": "电池"},
}


class DataFetchAgent(BaseFinanceAgent):
    """金融数据获取 Agent。"""

    agent_name: str = "data_fetch"

    def __init__(self, shared_memory=None):
        super().__init__(shared_memory=shared_memory)
        self._resolve_chain = None

    def _get_tools(self) -> list:
        return [
            get_stock_basic_info,
            get_stock_realtime_quote,
            get_financial_indicators,
            get_stock_history,
        ]

    def _get_system_prompt(self) -> str:
        return _DATA_FETCH_PROMPT

    @property
    def resolve_chain(self):
        """股票识别 LLM 链。"""
        if self._resolve_chain is None:
            prompt = ChatPromptTemplate.from_messages([
                ("system", _RESOLVE_STOCKS_PROMPT),
                ("human", "用户输入：{message}"),
            ])
            self._resolve_chain = prompt | get_model_for_agent("data_fetch") | StrOutputParser()
        return self._resolve_chain

    @staticmethod
    def extract_explicit_stocks(message: str) -> List[Dict[str, Any]]:
        """不调用模型，提取当前输入中明确出现的代码和常见证券名称。"""
        stocks: list[dict[str, str]] = []
        seen: set[str] = set()
        # 长名称优先，避免“贵州茅台”和“茅台”重复。
        for alias in sorted(KNOWN_A_SHARES, key=len, reverse=True):
            item = KNOWN_A_SHARES[alias]
            if alias in message and item["code"] not in seen:
                stocks.append(dict(item))
                seen.add(item["code"])
        for code in re.findall(
            r"(?<!\d)(60\d{4}|00\d{4}|30\d{4}|68\d{4}|8\d{5}|4\d{5})(?!\d)",
            message,
        ):
            if code not in seen:
                stocks.append({"code": code, "name": "", "industry": ""})
                seen.add(code)
        return stocks[:5]

    def resolve_stocks(self, message: str) -> List[Dict[str, Any]]:
        """用 LLM 识别用户消息中的股票名称，返回代码+名称+行业。

        Args:
            message: 用户原始消息

        Returns:
            股票列表，每个元素含 code/name/industry 字段
        """
        explicit = self.extract_explicit_stocks(message)
        if explicit:
            return explicit
        try:
            result = self.resolve_chain.invoke({"message": message})
            stocks = safe_parse_json(result, [])
            if not isinstance(stocks, list):
                return []
            # 过滤无效项，只保留6位代码
            valid = []
            for s in stocks:
                if isinstance(s, dict) and re.match(r"^\d{6}$", str(s.get("code", ""))):
                    valid.append({
                        "code": str(s["code"]),
                        "name": str(s.get("name", "")),
                        "industry": str(s.get("industry", "")),
                    })
            return valid[:5]  # 限制最多5只
        except Exception:
            return []

    def handle_single_stock(self, code: str) -> dict[str, Any]:
        """获取单只股票的全部金融数据并写入共享内存。

        供 LangGraph Send 并行节点调用。无 inter-stock 依赖，可并发执行。

        Args:
            code: 6位A股代码

        Returns:
            包含 basic_info / quote / indicators / history 及可能的 *_error 字段
        """
        entry: dict[str, Any] = {"code": code}

        # 基本信息
        try:
            raw = get_stock_basic_info.invoke({"stock_code": code})
            data = json.loads(raw) if isinstance(raw, str) else raw
            entry["basic_info"] = data
            if self.shared_memory and isinstance(data, dict) and "error" not in data:
                self.shared_memory.publish_fact(
                    f"stock_basic_info_{code}", data, source=self.agent_name,
                )
        except Exception as exc:
            entry["basic_info_error"] = str(exc)

        # 实时行情
        try:
            raw = get_stock_realtime_quote.invoke({"stock_code": code})
            data = json.loads(raw) if isinstance(raw, str) else raw
            entry["quote"] = data
            if self.shared_memory and isinstance(data, dict) and "error" not in data:
                self.shared_memory.publish_fact(
                    f"stock_quote_{code}", data, source=self.agent_name,
                )
        except Exception as exc:
            entry["quote_error"] = str(exc)

        # 财务指标
        try:
            raw = get_financial_indicators.invoke({"stock_code": code})
            data = json.loads(raw) if isinstance(raw, str) else raw
            entry["indicators"] = data
            if self.shared_memory and isinstance(data, dict) and "error" not in data:
                self.shared_memory.publish_fact(
                    f"financial_indicator_{code}", data, source=self.agent_name,
                )
        except Exception as exc:
            entry["indicators_error"] = str(exc)

        # 历史K线
        try:
            raw = get_stock_history.invoke({"stock_code": code})
            data = json.loads(raw) if isinstance(raw, str) else raw
            entry["history"] = data
            if self.shared_memory and isinstance(data, dict):
                # 无论成功还是失败都写入 shared_memory，让下游能读到错误详情
                self.shared_memory.publish_fact(
                    f"stock_history_{code}", data, source=self.agent_name,
                )
        except Exception as exc:
            entry["history_error"] = str(exc)
            if self.shared_memory:
                self.shared_memory.publish_fact(
                    f"stock_history_{code}",
                    {"error": f"工具调用异常：{exc}", "code": code},
                    source=self.agent_name,
                )

        return entry

    def handle(
        self,
        message: str,
        compressed_context: str = "",
        customer_id: str = "",
        chat_history: List[Dict[str, str]] | None = None,
        thread_id: str | None = None,
        memory_context: str = "",
    ) -> str:
        """获取金融数据并写入共享内存。"""
        # 从共享内存读取用户画像中的股票代码
        stock_codes: list[str] = []
        if self.shared_memory:
            user_profile = self.shared_memory.query("user_profile", {})
            if isinstance(user_profile, dict):
                stock_codes = user_profile.get("stock_codes", [])

        if not stock_codes:
            # 从用户消息中提取
            import re
            stock_codes = re.findall(r"(?<!\d)(60\d{4}|00\d{4}|30\d{4}|68\d{4}|8\d{5}|4\d{5})(?!\d)", message)

        if not stock_codes:
            return "未识别到股票代码，请提供A股代码（如600519、000001）后再获取数据。"

        # 获取每只股票的数据（复用 handle_single_stock，保持非并行场景兼容）
        results: list[dict[str, Any]] = [
            self.handle_single_stock(code) for code in stock_codes[:5]  # 限制最多5只
        ]

        # 生成摘要
        parts = [f"已获取 {len(results)} 只股票的金融数据："]
        for entry in results:
            code = entry["code"]
            quote = entry.get("quote", {})
            name = quote.get("name", entry.get("basic_info", {}).get("name", code))
            try:
                price = float(quote.get("price") or 0)
            except (TypeError, ValueError):
                price = 0.0
            try:
                change = float(quote.get("change_pct") or 0)
            except (TypeError, ValueError):
                change = 0.0
            status = "成功" if "error" not in quote else f"失败({quote.get('error', '')})"
            parts.append(f"  - {code}「{name}」价格:{price:.2f} 涨跌:{change:+.2f}% [{status}]")

        return "\n".join(parts)
