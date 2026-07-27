"""原生 Tool Calling 使用的金融槽位提取运行时。

职责：从用户输入中抽取结构化投资参数
- 风险偏好（R1-R5）
- 预算金额（元）
- 股票代码（A股6位代码）
- 持有时间（X天/周/月/年）
- 投资目标

先用正则快速抽取，再用LLM补全语义字段。
调用方负责注入已有画像与对话上下文，并合并返回的结构化结果。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Literal

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import BaseTool, tool

from finance_agent.config import get_model_for_agent, safe_parse_json


_PROFILE_EXTRACTION_PROMPT = """你是金融投顾系统的关键信息槽位提取专家。

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
- 如果不确定某名称对应的代码，不要编造，留空数组
- 结合“当前对话历史”理解“这只、这两只、它们、上述公司”等省略表达
- stock_codes 只包含当前问题实际指向的股票；不得仅因股票存在于长期画像就复制
- explicit_stock_codes 只包含当前用户输入中明确写出代码或股票名称的股票；
  仅通过对话历史补全的股票不能放入 explicit_stock_codes

## 输出格式
返回JSON：
{{
  "risk_preference": "R2 中低风险",
  "budget_amount": 100000,
  "stock_codes": ["600519", "600000"],
  "explicit_stock_codes": ["600519", "600000"],
  "holding_period": "3个月",
  "investment_goal": "稳健增值"
}}

如果某字段无法从用户输入中识别，对应值留空字符串或空数组。
"""


def extract_investment_goal(message: str) -> str:
    """确定性提取用户明确表达的投资目标，供所有快速路径复用。"""
    text = (message or "").strip()
    if not text:
        return ""

    # 优先读取“投资目标是/为……”等显式表达，并在标点或后续任务词前结束。
    explicit = re.search(
        r"投资目标\s*(?:是|为|：|:)\s*"
        r"([^，。；;！？!?]{2,20}?)"
        r"(?=(?:，|。|；|;|！|!|？|\?|如果|并且|然后|推荐|分析|配置|$))",
        text,
    )
    if explicit:
        return explicit.group(1).strip()

    # 没有标签时，仅匹配常见且语义明确的目标短语，避免把整句误存为画像。
    known_goals = (
        "长期稳健增值", "稳健增值", "长期增值", "财富增值", "资产增值",
        "资本增值", "保值增值", "养老储备", "教育储备", "现金流",
        "高收益", "长期收益", "短期收益",
    )
    return next((goal for goal in known_goals if goal in text), "")


class FinanceSlotsExtractor:
    """统一提取用户画像和股票等关键槽位。"""

    def __init__(self):
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

    def extract_profile(
        self,
        message: str,
        existing_profile: Dict[str, Any] | None = None,
        conversation_context: str = "",
    ) -> Dict[str, Any]:
        """从用户输入抽取结构化画像。

        Args:
            message: 用户输入
            existing_profile: 已有画像用于增量更新

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

        # 合并长期画像，但股票是本轮局部状态，不能从跨对话画像继承。
        if existing_profile:
            for key in profile:
                if key != "stock_codes" and key in existing_profile and existing_profile[key]:
                    profile[key] = existing_profile[key]

        # 当前消息中的目标优先于长期画像，且必须在所有快速返回之前提取。
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

        # 股票代码（6位A股代码，不用\b词边界，中文/数字交界处不生效）
        stock_codes = re.findall(r"(?<!\d)(60\d{4}|00\d{4}|30\d{4}|68\d{4}|8\d{5}|4\d{5})(?!\d)", message)
        if stock_codes:
            profile["stock_codes"] = list(dict.fromkeys(stock_codes))

        # 持有时间
        horizon_match = re.search(r"(\d+)\s*(天|周|个月|月|年)", message)
        if horizon_match:
            profile["holding_period"] = "".join(horizon_match.groups())

        # 当前消息已明确给出股票时，正则信息足以驱动数据流程，避免额外模型调用拖慢请求。
        if stock_codes:
            return profile

        # 行业/主题筛选请求没有具体画像可抽取，直接交给候选搜索，避免一次无意义的
        # LLM 调用把整个流程阻塞在“槽位提取”阶段。
        screening_markers = ("推荐", "选股", "筛选", "候选", "行业", "板块", "概念股")
        if any(marker in message for marker in screening_markers):
            profile["stock_codes"] = []
            return profile

        # 2. LLM 补全投资目标等语义字段
        try:
            result = self.extract_chain.invoke({
                "message": message,
                "existing": str(existing_profile or {}),
                "history": conversation_context or "无历史对话",
            })
            llm_profile = safe_parse_json(result, {})
            # LLM结果优先级高于正则
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

            # 股票可由当前消息或当前对话中的明确引用解析，但不能来自长期画像。
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
        return {
            "user_profile": profile,
            "resolved_stocks": resolved[:5],
            "explicit_stock_codes": explicit_codes,
        }

def create_extract_finance_slots_tool(
    extractor: FinanceSlotsExtractor,
    existing_profile: Dict[str, Any] | None = None,
    conversation_context: str = "",
) -> BaseTool:
    """创建绑定当前工作流状态的原生槽位提取工具。"""

    @tool("extract_finance_slots")
    def extract_finance_slots(
        intent: Literal["market_query", "stock_recommendation", "asset_allocation"],
        query: str,
    ) -> Dict[str, Any]:
        """从需要结构化参数的金融子请求中提取画像与股票身份。

        仅在具体个股行情/基本面、明确股票比较或资产配置时调用。
        板块行情、主题候选搜索、泛化选股和理财闲聊不得调用。
        """
        result = extractor.extract_slots(
            query,
            existing_profile=existing_profile or {},
            conversation_context=conversation_context,
        )
        return {"intent": intent, **result}

    return extract_finance_slots
