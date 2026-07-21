"""用户画像抽取 Agent。

职责：从用户输入中抽取结构化投资参数
- 风险偏好（R1-R5）
- 预算金额（元）
- 股票代码（A股6位代码）
- 持有时间（X天/周/月/年）
- 投资目标

先用正则快速抽取，再用LLM补全语义字段。
结果写入 SharedWorkingMemory 和 UserProfileCard。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from finance_agent.agents.base import BaseFinanceAgent
from finance_agent.config import get_model_for_agent, safe_parse_json


_PROFILE_EXTRACTION_PROMPT = """你是金融投顾系统的用户画像抽取专家。

## 职责
从用户输入中抽取结构化投资参数，补全正则无法识别的语义字段。

## 抽取字段
- risk_preference: 风险偏好 R1低风险/R2中低风险/R3中风险/R4中高风险/R5高风险
- budget_amount: 预算金额（元），如用户说"10万"则转换为100000
- stock_codes: A股6位数字代码列表，如 ["600519", "000001"]
- holding_period: 持有时间，如 "3个月"、"1年"
- investment_goal: 投资目标，如 "稳健增值"、"高收益"、"保本"

## 股票代码抽取规则
- 用户可能直接输入6位数字代码，如"600519"、"000001"
- 用户也可能输入中文股票名称，如"贵州茅台"、"浦发银行"
- 你必须将中文股票名称映射为对应的A股6位数字代码
- 常见示例：贵州茅台→600519，浦发银行→600000，招商银行→600036，中国平安→601318
- 如果不确定某名称对应的代码，不要编造，留空数组
- stock_codes 只能包含“当前用户输入”明确提到的股票，不要从已有画像复制旧股票

## 输出格式
返回JSON：
{{
  "risk_preference": "R2 中低风险",
  "budget_amount": 100000,
  "stock_codes": ["600519", "600000"],
  "holding_period": "3个月",
  "investment_goal": "稳健增值"
}}

如果某字段无法从用户输入中识别，对应值留空字符串或空数组。
"""


class ProfileExtractionAgent(BaseFinanceAgent):
    """用户画像抽取 Agent。"""

    agent_name: str = "profile"

    def __init__(self, shared_memory=None):
        super().__init__(shared_memory=shared_memory)
        self._extract_chain = None

    def _get_tools(self) -> list:
        return []

    def _get_system_prompt(self) -> str:
        return _PROFILE_EXTRACTION_PROMPT

    @property
    def extract_chain(self):
        """独立的画像抽取链。"""
        if self._extract_chain is None:
            prompt = ChatPromptTemplate.from_messages([
                ("system", _PROFILE_EXTRACTION_PROMPT),
                ("human", "用户输入：{message}\n\n已有画像信息：{existing}\n\n请抽取/更新用户画像："),
            ])
            self._extract_chain = prompt | get_model_for_agent("profile") | StrOutputParser()
        return self._extract_chain

    def extract_profile(
        self,
        message: str,
        existing_profile: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """从用户输入抽取结构化画像。

        Args:
            message: 用户输入
            existing_profile: 已有画像（用于增量更新）

        Returns:
            结构化画像字典
        """
        # 1. 正则快速抽取
        profile: Dict[str, Any] = {
            "risk_preference": "",
            "budget_amount": 0.0,
            "stock_codes": [],
            "holding_period": "",
            "investment_goal": "",
        }

        # 合并已有画像
        if existing_profile:
            for key in profile:
                if key in existing_profile and existing_profile[key]:
                    profile[key] = existing_profile[key]

        msg_lower = message.lower()

        # 风险偏好
        risk_map = [
            ("R5 高风险", ["r5", "高风险", "进取", "激进"]),
            ("R4 中高风险", ["r4", "中高风险", "积极"]),
            ("R3 中风险", ["r3", "中风险", "平衡"]),
            ("R2 中低风险", ["r2", "中低风险", "稳健"]),
            ("R1 低风险", ["r1", "低风险", "保守"]),
        ]
        for value, keywords in risk_map:
            if any(kw in msg_lower for kw in keywords):
                profile["risk_preference"] = value
                break

        # 预算金额
        wan_match = re.search(r"(\d+(?:\.\d+)?)\s*万", message)
        if wan_match:
            profile["budget_amount"] = float(wan_match.group(1)) * 10000
        else:
            yuan_match = re.search(r"(\d+(?:\.\d+)?)\s*元", message)
            if yuan_match:
                val = float(yuan_match.group(1))
                if val >= 100:
                    profile["budget_amount"] = val

        # 股票代码（6位A股代码，不用\b词边界，中文/数字交界处不生效）
        stock_codes = re.findall(r"(?<!\d)(60\d{4}|00\d{4}|30\d{4}|68\d{4}|8\d{5}|4\d{5})(?!\d)", message)
        # 高频名称采用确定性映射，避免 LLM/网络异常时错误沿用上一轮股票。
        known_stocks = {
            "贵州茅台": "600519", "茅台": "600519", "浦发银行": "600000",
            "招商银行": "600036", "招行": "600036", "中国平安": "601318",
            "平安银行": "000001", "五粮液": "000858", "宁德时代": "300750",
        }
        for name, code in known_stocks.items():
            if name in message and code not in stock_codes:
                stock_codes.append(code)
        if stock_codes:
            profile["stock_codes"] = list(dict.fromkeys(stock_codes))

        # 持有时间
        horizon_match = re.search(r"(\d+)\s*(天|周|个月|月|年)", message)
        if horizon_match:
            profile["holding_period"] = "".join(horizon_match.groups())

        # 当前消息已明确给出股票时，正则信息足以驱动数据流程，避免额外模型调用拖慢请求。
        if stock_codes:
            return profile

        # 2. LLM 补全投资目标等语义字段
        try:
            result = self.extract_chain.invoke({
                "message": message,
                "existing": str(existing_profile or {}),
            })
            llm_profile = safe_parse_json(result, {})
            # LLM结果优先级高于正则（仅当LLM识别到时）
            if llm_profile.get("investment_goal"):
                profile["investment_goal"] = llm_profile["investment_goal"]
            if llm_profile.get("risk_preference") and not profile["risk_preference"]:
                profile["risk_preference"] = llm_profile["risk_preference"]
            if llm_profile.get("budget_amount") and not profile["budget_amount"]:
                try:
                    profile["budget_amount"] = float(llm_profile["budget_amount"])
                except (ValueError, TypeError):
                    pass
            if llm_profile.get("holding_period") and not profile["holding_period"]:
                profile["holding_period"] = llm_profile["holding_period"]

            # 只使用当前消息识别结果，避免旧画像股票污染本轮分析。
            llm_codes = llm_profile.get("stock_codes", [])
            if llm_codes:
                current_codes = list(stock_codes)
                for code in llm_codes:
                    if isinstance(code, str) and re.fullmatch(r"\d{6}", code) and code not in current_codes:
                        current_codes.append(code)
                profile["stock_codes"] = current_codes

        except Exception:
            pass

        return profile

    def handle(
        self,
        message: str,
        compressed_context: str = "",
        customer_id: str = "",
        chat_history: List[Dict[str, str]] | None = None,
        thread_id: str | None = None,
        memory_context: str = "",
    ) -> str:
        """抽取画像并写入共享内存。"""
        # 从共享内存读取已有画像
        existing = {}
        if self.shared_memory:
            existing = self.shared_memory.query("user_profile", {}) or {}

        profile = self.extract_profile(message, existing)

        # 写入共享内存
        if self.shared_memory:
            self.shared_memory.publish_fact("user_profile", profile, source=self.agent_name)

        # 生成摘要回复
        parts = ["已抽取用户画像："]
        if profile.get("risk_preference"):
            parts.append(f"  风险偏好：{profile['risk_preference']}")
        if profile.get("budget_amount"):
            parts.append(f"  预算金额：{profile['budget_amount']:,.0f} 元")
        if profile.get("stock_codes"):
            parts.append(f"  关注股票：{', '.join(profile['stock_codes'])}")
        if profile.get("holding_period"):
            parts.append(f"  持有时间：{profile['holding_period']}")
        if profile.get("investment_goal"):
            parts.append(f"  投资目标：{profile['investment_goal']}")

        if len(parts) == 1:
            parts.append("  暂未识别到明确的投资参数")

        return "\n".join(parts)
