"""Profile Agent —— 从用户输入中抽取结构化投资画像与股票身份。

职责：
- 从用户输入抽取结构化投资参数（risk_preference, budget_amount, stock_codes, holding_period, investment_goal）
- 识别股票身份（code, name, industry）
- 提取板块/行业关键词（sector_keywords），服务于东方财富板块搜索
- 正则快速路径 + LLM 语义回退（保留现有两级策略）
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from finance_agent.agents.base import ProceduralAgent
from finance_agent.config import get_model_for_agent, safe_parse_json


_PROFILE_EXTRACTION_PROMPT = """你是金融投顾系统的关键信息槽位提取专家。

## 职责
从用户输入中抽取结构化投资参数，补全正则无法识别的语义字段。

## 输出格式
{"risk_preference": "R3 中风险", "budget_amount": 100000, "stock_codes": ["600519"],
 "holding_period": "6个月", "investment_goal": "寻找高成长股票",
 "sector_keywords": ["新能源", "AI"], "explicit_stock_codes": ["600519"]}

## 规则
- risk_preference 必须是 R1-R5 格式，如"R3 中风险"
- budget_amount 是数字金额（元），不是字符串
- stock_codes 是6位A股代码列表
- holding_period 是字符串，如"3个月"
- investment_goal 是自然语言描述，从用户输入推断，如"稳健增值"、"高收益"
- sector_keywords 是从输入中提取的板块/行业主题词列表
- explicit_stock_codes 是用户消息中明确出现的股票代码
- 无法确定的字段返回空值
"""


def extract_investment_goal(message: str) -> str:
    """从用户消息中提取投资目标。"""
    msg_lower = message.lower()
    goal_map = [
        ("稳健增值", ["稳健", "保本", "低风险", "保守", "稳妥"]),
        ("平衡增长", ["平衡", "适中", "中等风险"]),
        ("获取收益", ["收益", "分红", "派息"]),
        ("高收益", ["高收益", "激进", "进取", "高风险"]),
        ("长期投资", ["长期", "养老", "退休"]),
        ("中短期交易", ["短期", "快进快出", "波段"]),
    ]
    for goal, keywords in goal_map:
        if any(kw in msg_lower for kw in keywords):
            return goal
    return ""


class ProfileAgent(ProceduralAgent):
    """统一提取用户画像和股票等关键槽位。"""

    agent_name: str = "profile"

    def __init__(self, shared_memory=None):
        super().__init__(shared_memory=shared_memory)
        self._extract_chain = None

    @property
    def extract_chain(self):
        """独立的画像抽取链。"""
        if self._extract_chain is None:
            prompt = ChatPromptTemplate.from_messages([
                ("system", _PROFILE_EXTRACTION_PROMPT),
                (
                    "human",
                    "当前对话历史：\n{history}\n\n"
                    "当前用户输入：{message}\n\n"
                    "已有长期画像：{existing}\n\n"
                    "请抽取本轮画像和股票引用：",
                ),
            ])
            self._extract_chain = prompt | get_model_for_agent("slot_extraction") | StrOutputParser()
        return self._extract_chain

    def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """从 State 中提取画像与股票身份。"""
        message = state.get("user_message", "")
        existing_profile = state.get("user_profile", {}) or {}
        conversation_context = state.get("memory_context", "") or ""

        result = self.extract_slots(message, existing_profile, conversation_context)
        state["user_profile"] = result["user_profile"]
        state["resolved_stocks"] = result["resolved_stocks"]
        if result.get("sector_keywords"):
            state["sector_keywords"] = result["sector_keywords"]
        return state

    def extract_profile(
        self,
        message: str,
        existing_profile: Dict[str, Any] | None = None,
        conversation_context: str = "",
    ) -> Dict[str, Any]:
        """从用户输入抽取结构化画像。"""
        profile: Dict[str, Any] = {
            "risk_preference": "",
            "budget_amount": 0.0,
            "stock_codes": [],
            "holding_period": "",
            "investment_goal": "",
            "sector_keywords": [],
        }

        # 合并长期画像，但股票是本轮局部状态，不能从跨对话画像继承。
        if existing_profile:
            for key in profile:
                if key not in ("stock_codes", "sector_keywords") and key in existing_profile and existing_profile[key]:
                    profile[key] = existing_profile[key]

        # 当前消息中的目标优先于长期画像
        current_goal = extract_investment_goal(message)
        if current_goal:
            profile["investment_goal"] = current_goal

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

        # 股票代码（6位A股代码）
        stock_codes = re.findall(r"(?<!\d)(60\d{4}|00\d{4}|30\d{4}|68\d{4}|8\d{5}|4\d{5})(?!\d)", message)
        if stock_codes:
            profile["stock_codes"] = list(dict.fromkeys(stock_codes))

        # 持有时间
        horizon_match = re.search(r"(\d+)\s*(天|周|个月|月|年)", message)
        if horizon_match:
            profile["holding_period"] = "".join(horizon_match.groups())

        # 板块/行业关键词
        sector_markers = [
            "新能源", "AI", "人工智能", "芯片", "半导体", "医药", "医疗",
            "消费", "白酒", "金融", "银行", "保险", "地产", "房地产",
            "科技", "互联网", "汽车", "军工", "农业", "化工", "钢铁",
            "光伏", "锂电", "储能", "机器人", "元宇宙", "碳中和",
        ]
        matched = [kw for kw in sector_markers if kw in message]
        if matched:
            profile["sector_keywords"] = matched

        # 当前消息已明确给出股票时，正则信息足以驱动数据流程
        if stock_codes:
            return profile

        # 行业/主题筛选请求没有具体画像可抽取
        screening_markers = ("推荐", "选股", "筛选", "候选", "行业", "板块", "概念股")
        if any(marker in message for marker in screening_markers):
            profile["stock_codes"] = []
            return profile

        # LLM 补全语义字段
        try:
            result = self.extract_chain.invoke({
                "message": message,
                "existing": str(existing_profile or {}),
                "history": conversation_context or "无历史对话",
            })
            llm_profile = safe_parse_json(result, {})
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
            if llm_profile.get("sector_keywords") and not profile.get("sector_keywords"):
                profile["sector_keywords"] = llm_profile["sector_keywords"]

            llm_codes = llm_profile.get("stock_codes", [])
            if llm_codes:
                current_codes = list(stock_codes)
                for code in llm_codes:
                    if isinstance(code, str) and re.fullmatch(r"\d{6}", code) and code not in current_codes:
                        current_codes.append(code)
                profile["stock_codes"] = current_codes

            explicit_llm_codes = llm_profile.get("explicit_stock_codes", [])
            profile["_explicit_stock_codes"] = [
                code for code in explicit_llm_codes
                if isinstance(code, str) and re.fullmatch(r"\d{6}", code)
            ][:5]

        except Exception:
            pass

        return profile

    @staticmethod
    def extract_explicit_stocks(message: str) -> List[Dict[str, Any]]:
        """提取当前输入中明确出现的股票代码。"""
        stocks: list[dict[str, str]] = []
        seen: set[str] = set()
        for code in re.findall(
            r"(?<!\d)(60\d{4}|00\d{4}|30\d{4}|68\d{4}|8\d{5}|4\d{5})(?!\d)",
            message,
        ):
            if code not in seen:
                stocks.append({"code": code, "name": "", "industry": ""})
                seen.add(code)
        return stocks[:5]

    def extract_slots(
        self,
        message: str,
        existing_profile: Dict[str, Any] | None = None,
        conversation_context: str = "",
    ) -> Dict[str, Any]:
        """一次返回画像槽位与结构化股票身份。"""
        profile = self.extract_profile(message, existing_profile, conversation_context)
        stocks = self.extract_explicit_stocks(message)
        explicit_codes = list(dict.fromkeys(
            [stock["code"] for stock in stocks]
            + list(profile.pop("_explicit_stock_codes", []))
        ))[:5]
        stock_by_code = {stock["code"]: stock for stock in stocks}
        resolved = [
            stock_by_code.get(code, {"code": code, "name": "", "industry": ""})
            for code in profile.get("stock_codes", [])
        ]
        for stock in stocks:
            if stock["code"] not in {item["code"] for item in resolved}:
                resolved.append(stock)
        profile["stock_codes"] = [item["code"] for item in resolved[:5]]
        sector_keywords = profile.pop("sector_keywords", []) or []
        return {
            "user_profile": profile,
            "resolved_stocks": resolved[:5],
            "explicit_stock_codes": explicit_codes,
            "sector_keywords": sector_keywords,
        }
