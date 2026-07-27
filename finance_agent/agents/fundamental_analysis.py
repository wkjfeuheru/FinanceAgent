"""基本面分析 Agent。

职责：基于财务指标分析基本面情况
- 盈利能力（ROE、净利率、毛利率）
- 成长性（营收增长、利润增长）
- 估值水平（PE、PB）
- 财务健康（负债率、流动比率）

分析结果写入共享内存供资产配置Agent参考。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from finance_agent.agents.base import BaseFinanceAgent
from finance_agent.config import get_model_for_agent, safe_parse_json


def _safe_score(value: Any, default: float = 50.0) -> float:
    """Convert an LLM score to float while tolerating null/empty/invalid values."""
    try:
        score = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(100.0, score))


_FUNDAMENTAL_ANALYSIS_PROMPT = """你是金融基本面分析专家。

## 身份
你负责分析A股上市公司的基本面情况，为投资决策提供依据。

## 分析维度

### 1. 盈利能力
- ROE（净资产收益率）：>15% 优秀，10-15% 良好，<10% 一般
- 净利率：反映盈利转化效率
- 毛利率：反映产品竞争力

### 2. 成长性
- 营收增长率：>20% 高成长，10-20% 稳健，<10% 低成长
- 净利润增长率：判断成长持续性

### 3. 估值水平
- PE（市盈率）：与行业均值对比
- PB（市净率）：判断是否高估/低估

### 4. 财务健康
- 资产负债率：<50% 健康，50-70% 中性，>70% 风险较高
- 流动比率/速动比率：>2 流动性好

## 输出格式
返回JSON：
{{
  "code": "股票代码",
  "name": "股票名称",
  "profitability": {{"score": 0-100, "analysis": "..."}},
  "growth": {{"score": 0-100, "analysis": "..."}},
  "valuation": {{"score": 0-100, "analysis": "..."}},
  "financial_health": {{"score": 0-100, "analysis": "..."}},
  "overall_score": 0-100,
  "rating": "推荐/中性/谨慎",
  "advantages": ["优势1", "优势2"],
  "risks": ["风险1", "风险2"],
  "summary": "一句话总结"
}}

## 规则
- 基于共享上下文中的财务指标数据进行分析，不要编造数据
- 如果数据缺失，明确指出
- 评级标准：overall_score >= 75 推荐，60-75 中性，<60 谨慎
- 语言要求：使用正式、专业的书面中文。不得使用口语化或网络用语表述。
  优势/风险描述应使用"盈利能力突出""估值处于合理区间""财务结构稳健"
  "流动性需关注"等专业措辞。summary 必须是一句完整的、有信息量的
  专业判断，不得使用空泛口语。"""


class FundamentalAnalysisAgent(BaseFinanceAgent):
    """基本面分析 Agent。"""

    agent_name: str = "fundamental"

    def __init__(self, shared_memory=None, checkpointer=None):
        super().__init__(shared_memory=shared_memory, checkpointer=checkpointer)
        self._analysis_chain = None

    def _get_tools(self) -> list:
        return []

    def _get_system_prompt(self) -> str:
        return _FUNDAMENTAL_ANALYSIS_PROMPT

    @property
    def analysis_chain(self):
        """独立的基本面分析链。"""
        if self._analysis_chain is None:
            prompt = ChatPromptTemplate.from_messages([
                ("system", _FUNDAMENTAL_ANALYSIS_PROMPT),
                ("human", "股票财务数据：\n{financial_data}\n\n请进行基本面分析："),
            ])
            self._analysis_chain = prompt | get_model_for_agent("fundamental") | StrOutputParser()
        return self._analysis_chain

    def analyze(self, stock_code: str, financial_data: Dict[str, Any]) -> Dict[str, Any]:
        """分析单只股票的基本面。

        Args:
            stock_code: 股票代码
            financial_data: 财务指标数据（来自共享内存）

        Returns:
            结构化分析结果
        """
        try:
            result = self.analysis_chain.invoke({
                "financial_data": json.dumps(financial_data, ensure_ascii=False, default=str)
                if isinstance(financial_data, dict) else str(financial_data),
            })
            parsed = safe_parse_json(result, {
                "code": stock_code,
                "overall_score": 50,
                "rating": "中性",
                "summary": "基本面分析解析失败",
            })
        except Exception:
            parsed = {
                "code": stock_code,
                "overall_score": 50,
                "rating": "中性",
                "summary": "基本面分析执行异常",
            }

        parsed["code"] = stock_code
        parsed["overall_score"] = _safe_score(parsed.get("overall_score"))
        return parsed

    def handle_single_stock(self, code: str) -> Dict[str, Any]:
        """分析单只股票的基本面并写入共享内存。

        供 LangGraph Send 并行节点调用。从共享内存读取上游 data_fetch 写入的
        financial_indicator_{code} 和 stock_basic_info_{code}，复用 self.analyze
        进行 LLM 分析，结果发布回共享内存。无 inter-stock 依赖，可并发执行。

        Args:
            code: 6位A股代码

        Returns:
            基本面分析结果 dict
        """
        if not self.shared_memory:
            return {"code": code, "rating": "未知", "summary": "无共享内存"}

        indicators = self.shared_memory.query(f"financial_indicator_{code}", {})
        basic_info = self.shared_memory.query(f"stock_basic_info_{code}", {})

        if not indicators and not basic_info:
            result = {
                "code": code,
                "rating": "未知",
                "summary": "无财务数据，无法分析",
                "overall_score": 50,
            }
        else:
            financial_data = {
                "code": code,
                "basic_info": basic_info or {},
                "indicators": indicators or {},
            }
            result = self.analyze(code, financial_data)

        # 固定保留原始指标，报告展示不依赖 LLM 是否主动复述数据。
        result["name"] = basic_info.get("name", code) if isinstance(basic_info, dict) else code
        result["indicators"] = indicators if isinstance(indicators, dict) else {}
        quote = self.shared_memory.query(f"stock_quote_{code}", {})
        result["quote"] = quote if isinstance(quote, dict) else {}
        candidate = self.shared_memory.query(f"stock_search_candidate_{code}", {})
        result["search_candidate"] = candidate if isinstance(candidate, dict) else {}

        # 写入共享内存
        self.shared_memory.publish_fact(
            f"fundamental_analysis_{code}", result, source=self.agent_name,
        )
        return result

    def handle(
        self,
        message: str,
        customer_id: str = "",
        chat_history: List[Dict[str, str]] | None = None,
        thread_id: str | None = None,
        memory_context: str = "",
    ) -> str:
        """分析所有关注股票的基本面。"""
        if not self.shared_memory:
            return "基本面分析需要共享内存支持。"

        # 从共享内存读取财务指标
        stock_codes: list[str] = []
        user_profile = self.shared_memory.query("user_profile", {})
        if isinstance(user_profile, dict):
            stock_codes = user_profile.get("stock_codes", [])

        if not stock_codes:
            return "未识别到需要分析的股票代码。"

        # 复用 handle_single_stock，保持非并行场景兼容
        analyses: list[Dict[str, Any]] = [
            self.handle_single_stock(code) for code in stock_codes[:5]
        ]

        # 生成摘要
        parts = [f"已完成 {len(analyses)} 只股票的基本面分析："]
        for a in analyses:
            code = a.get("code", "")
            rating = a.get("rating", "未知")
            score = _safe_score(a.get("overall_score"), 0.0)
            summary = a.get("summary", "")
            parts.append(f"  - {code} 评级：{rating}（{score:.0f}分）| {summary}")

        return "\n".join(parts)
