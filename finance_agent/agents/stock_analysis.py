"""股票综合分析 Agent。

职责：根据用户输入自主决策，执行基本面分析、技术面分析或两者兼有。
- 基本面：盈利能力（ROE、净利率、毛利率）、成长性、估值（PE、PB）、财务健康
- 技术面：MACD、KDJ、RSI、BOLL、MA（均线）、WR（威廉指标）

通过 ReAct Agent 接收近期对话摘要 + 当前问题，自主 tool calling 选择
分析工具。当无法判断意图时主动追问。分析结果写入 AdvisorState。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from langchain_core.messages import ToolMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool

from finance_agent.agents.base import ReActAgent
from finance_agent.config import get_model_for_agent, safe_parse_json
from finance_agent.orchestrator.tools.technical import compute_all_indicators


def _safe_score(value: Any, default: float = 50.0) -> float:
    """Convert an LLM score to float while tolerating null/empty/invalid values."""
    try:
        score = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(100.0, score))


# 技术面关键词 → 标准指标名映射（用于确定性兜底，避免 LLM 漏调工具）
# 英文关键词用 \b 单词边界匹配，避免 "ma" 误匹配 "macd" 等子串问题
_TECH_KEYWORD_PAIRS: list[tuple[str, str]] = [
    # 具体指标名
    ("macd", "MACD"),
    ("kdj", "KDJ"),
    ("rsi", "RSI"),
    ("boll", "BOLL"),
    ("布林", "BOLL"),
    ("威廉", "WR"),
    ("均线", "MA"),
    # 通用技术面词（无具体指标，应计算全部）
    ("技术面", ""),
    ("技术指标", ""),
    ("走势", ""),
    ("形态", ""),
    ("趋势", ""),
    ("买卖信号", ""),
    ("超买", ""),
    ("超卖", ""),
    ("k线", ""),
    ("K线", ""),
]


def _detect_technical_intent(user_message: str) -> list[str]:
    """从用户消息中检测是否包含技术面分析需求，返回请求的指标名列表。

    若仅命中通用技术面词（如"技术面/走势"）而无具体指标名，返回 [""] 表示
    需要技术面分析但未指定具体指标（应计算全部默认指标）。
    完全未命中则返回空列表。
    """
    import re as _re
    if not user_message:
        return []
    specific: list[str] = []
    general_hit = False

    for keyword, standard in _TECH_KEYWORD_PAIRS:
        # 英文关键词用 ASCII 字母边界匹配（避免 "ma" 误匹配 "macd"），
        # 同时支持中英文混排（如"的MACD指标"）。
        if keyword.isascii():
            pattern = (
                r"(?<![a-zA-Z])" + _re.escape(keyword) + r"(?![a-zA-Z])"
            )
            found = bool(_re.search(pattern, user_message, _re.IGNORECASE))
        else:
            found = keyword in user_message
        if found:
            if standard:
                if standard not in specific:
                    specific.append(standard)
            else:
                general_hit = True

    if specific:
        return specific
    if general_hit:
        return [""]  # 需要技术面分析但未指定具体指标
    return []


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
- 基于提供的财务指标数据进行分析，不要编造数据
- 如果数据缺失，明确指出
- 评级标准：overall_score >= 75 推荐，60-75 中性，<60 谨慎
- 语言要求：使用正式、专业的书面中文。不得使用口语化或网络用语表述。
  优势/风险描述应使用"盈利能力突出""估值处于合理区间""财务结构稳健"
  "流动性需关注"等专业措辞。summary 必须是一句完整的、有信息量的
  专业判断，不得使用空泛口语。"""


_STOCK_ANALYSIS_SYSTEM_PROMPT = """你是股票综合分析专家，拥有基本面分析和技术面分析两种专业能力。

## 可用工具
- `analyze_fundamentals`: 基于财务指标（ROE/PE/PB/利润增速/负债率等）分析基本面。
  适用场景：估值判断、盈利能力评估、财务健康检查、成长性分析。

- `analyze_technicals`: 基于K线数据计算技术指标（MACD/KDJ/RSI/BOLL/MA/WR）并解读走势。
  适用场景：买卖信号、趋势判断、超买超卖、支撑压力位。
  可通过 indicators 参数指定需要的指标，
  如 `analyze_technicals(stock_code="600519", indicators=["MACD","KDJ"])`。

## 决策规则
1. 用户明确提到"基本面/估值/财务/盈利/ROE/PE/PB/负债率"等关键词
   → 只调用 `analyze_fundamentals`
2. 用户明确提到"技术面/走势/形态/K线/趋势/买卖信号/超买/超卖"或
   具体指标名（MACD/KDJ/RSI/布林/BOLL/均线/MA/WR/威廉）
   → 只调用 `analyze_technicals`。
   若用户指定了具体指标，通过 indicators 参数传入
3. 用户说"全面分析/综合分析/整体评估"或同时提及两方面关键词
   → 调用两个工具
4. 若用户指定的指标在技术面工具不覆盖范围内，只计算能支持的指标并如实说明
5. 无法从对话判断意图 → 不要调用任何工具，追问
   "请问您需要基本面分析（估值、盈利能力等）还是技术面分析（MACD、KDJ等指标走势）？"

## 输出规则
- 只输出用户关心的分析维度，严格对应用户提问范围
- 用户只问技术面 → 回复只含技术面，不要夹杂基本面内容；反之同理
- 用户指定了具体指标 → 只输出这些指标的结果和解读，不要把全部指标堆砌上去
- 数据缺失时明确指出限制，不编造数据
- 使用正式、专业的书面中文"""


class StockAnalysisAgent(ReActAgent):
    """股票综合分析 Agent —— 基本面 + 技术面，ReAct 自主决策。"""

    agent_name: str = "stock_analysis"
    max_reasoning_steps: int = 6
    per_invoke_timeout: float = 60.0

    def __init__(self, checkpointer=None):
        super().__init__(checkpointer=checkpointer)
        # 基本面分析链（保持独立，供 tool 内部复用）
        self._fundamental_chain = None
        self._current_stock_data: Dict[str, Any] = {}

    # 从 AdvisorState 读取股票数据并执行逐股分析。
    def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """从显式状态读取股票并写回综合分析结果。"""
        import re

        stock_data = state.get("stock_data", {}) or {}
        user_message = str(state.get("requirement", "") or state.get("user_message", ""))
        codes = [
            item.get("code") for item in state.get("resolved_stocks", [])
            if isinstance(item, dict) and item.get("code")
        ]
        if not codes:
            codes = re.findall(
                r"(?<!\d)(60\d{4}|00\d{4}|30\d{4}|68\d{4}|8\d{5}|4\d{5})(?!\d)",
                user_message,
            )
        analyses = [
            self.handle_single_stock(
                str(code),
                user_message=user_message,
                memory_context=str(state.get("memory_context", "")),
                chat_history=state.get("chat_history"),
                stock_data=stock_data,
            )
            for code in codes[:5]
        ]
        state["stock_analysis"] = {item["code"]: item for item in analyses if item.get("code")}
        state["technical_analysis"] = {
            item["code"]: item["technical_analysis"]
            for item in analyses
            if item.get("code") and item.get("technical_analysis")
        }
        content = self._format_analysis_response(analyses)
        state["agent_response"] = content
        state.setdefault("intent_results", {})["market_query"] = {
            "status": "success" if analyses else "degraded",
            "content": content,
        }
        state["intent_results"].setdefault("stock_recommendation", state["intent_results"]["market_query"])
        return state

    # 将逐股结果整理为总管可合并的文本。
    def _format_analysis_response(self, analyses: list[Dict[str, Any]]) -> str:
        if not analyses:
            return "未识别到需要分析的股票代码。"
        parts = [f"已完成 {len(analyses)} 只股票的分析："]
        for item in analyses:
            parts.append(
                f"- {item.get('code', '')} 评级：{item.get('rating', '未知')}"
                f"（{_safe_score(item.get('overall_score'), 0.0):.0f}分）｜{item.get('summary', '')}"
            )
        return "\\n".join(parts)

    # ── 工具定义（闭包捕获 self，在 _get_tools() 中构造）──

    def _get_tools(self) -> list:
        agent_self = self

        @tool
        def analyze_fundamentals(stock_code: str) -> str:
            """对指定A股进行基本面分析。

            基于财务指标数据（ROE/PE/PB/净利率/营收增长率/负债率/流动比率等），
            从盈利能力、成长性、估值水平、财务健康四个维度评估。
            适用场景：用户关注估值、盈利能力、财务健康、成长性。

            Args:
                stock_code: 6位A股代码，如 600519

            Returns:
                JSON 格式的结构化分析结果
            """
            item = agent_self._current_stock_data.get(stock_code, {})
            indicators = item.get("indicators", {}) if isinstance(item, dict) else {}
            basic_info = item.get("basic_info", {}) if isinstance(item, dict) else {}

            if not indicators and not basic_info:
                return json.dumps({
                    "code": stock_code, "rating": "未知", "overall_score": 50,
                    "summary": "无财务数据，无法分析",
                }, ensure_ascii=False)

            financial_data = {
                "code": stock_code,
                "basic_info": basic_info or {},
                "indicators": indicators or {},
            }

            return agent_self._run_fundamental_chain(stock_code, financial_data)

        @tool
        def analyze_technicals(
            stock_code: str,
            indicators: list[str] | None = None,
        ) -> str:
            """对指定A股进行技术面分析。

            基于历史K线数据（最近一年日K线）计算指定技术指标并解读走势。
            可计算 MACD/KDJ/RSI/BOLL/MA/WR 六种指标。
            适用场景：用户关注走势、买卖信号、超买超卖、支撑压力位、趋势判断。

            Args:
                stock_code: 6位A股代码，如 600519
                indicators: 需要的指标列表，如 ["MACD","KDJ"]。
                            None 或空列表表示计算全部 6 个默认指标。

            Returns:
                JSON 格式的结构化技术面分析结果
            """
            item = agent_self._current_stock_data.get(stock_code, {})
            history = item.get("history", {}) if isinstance(item, dict) else {}
            if not history or "error" in history:
                return json.dumps({
                    "error": "无K线历史数据，无法进行技术面分析",
                    "code": stock_code,
                }, ensure_ascii=False)

            data_points = history.get("data")
            if not isinstance(data_points, list) or len(data_points) < 30:
                return json.dumps({
                    "error": f"K线数据不足（仅 {len(data_points) if isinstance(data_points, list) else 0} 条），最少需要 30 条",
                    "code": stock_code,
                }, ensure_ascii=False)

            try:
                high = [float(d["high"]) for d in data_points]
                low = [float(d["low"]) for d in data_points]
                close = [float(d["close"]) for d in data_points]
            except (KeyError, ValueError, TypeError) as exc:
                return json.dumps({
                    "error": f"K线数据格式异常：{exc}",
                    "code": stock_code,
                }, ensure_ascii=False)

            try:
                result = compute_all_indicators(high, low, close, indicators)
            except Exception as exc:
                return json.dumps({
                    "error": f"技术指标计算失败：{exc}",
                    "code": stock_code,
                }, ensure_ascii=False)

            return json.dumps(result, ensure_ascii=False)

        return [analyze_fundamentals, analyze_technicals]

    def _get_system_prompt(self) -> str:
        return _STOCK_ANALYSIS_SYSTEM_PROMPT

    # ── 基本面分析 LLM 链（tool 内部复用）──

    @property
    def fundamental_chain(self):
        """独立的基本面分析 LLM 链。"""
        if self._fundamental_chain is None:
            prompt = ChatPromptTemplate.from_messages([
                ("system", _FUNDAMENTAL_ANALYSIS_PROMPT),
                ("human", "股票财务数据：\n{financial_data}\n\n请进行基本面分析："),
            ])
            self._fundamental_chain = (
                prompt
                | get_model_for_agent("fundamental")
                | StrOutputParser()
            )
        return self._fundamental_chain

    def _run_fundamental_chain(
        self, stock_code: str, financial_data: Dict[str, Any],
    ) -> str:
        """执行基本面分析 LLM 链并返回 JSON 字符串。"""
        try:
            result = self.fundamental_chain.invoke({
                "financial_data": json.dumps(
                    financial_data, ensure_ascii=False, default=str,
                ) if isinstance(financial_data, dict) else str(financial_data),
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
        return json.dumps(parsed, ensure_ascii=False)

    # ── 上下文构建 ──

    def _build_analysis_context(
        self,
        code: str,
        indicators: Dict[str, Any],
        basic_info: Dict[str, Any],
        history: Dict[str, Any],
        user_message: str,
        memory_context: str,
    ) -> str:
        """构建 ReAct Agent 的输入上下文。"""

        parts = []

        # 用户当前问题
        if user_message:
            parts.append(f"## 当前用户问题\n{user_message}")
        else:
            name = (basic_info.get("name") or code) if isinstance(basic_info, dict) else code
            parts.append(f"## 当前用户问题\n请分析股票 {code}「{name}」")

        # 对话上下文
        if memory_context:
            # 截断过长的上下文
            ctx = memory_context[:3000] if len(memory_context) > 3000 else memory_context
            parts.append(f"## 近期对话摘要\n{ctx}")

        # 可用数据描述
        available = []
        has_financial = (
            isinstance(indicators, dict)
            and indicators
            and "error" not in indicators
        )
        has_history = (
            isinstance(history, dict)
            and history.get("data")
            and "error" not in history
        )
        history_count = (
            len(history.get("data", []))
            if isinstance(history, dict) and isinstance(history.get("data"), list)
            else 0
        )

        if has_financial:
            available.append("财务指标数据 已就绪（ROE/PE/PB/营收增速/负债率等）")
        else:
            available.append("财务指标数据 缺失或不可用")
        if has_history:
            available.append(f"K线历史数据 已就绪（最近 {history_count} 个交易日）")
        else:
            available.append("K线历史数据 缺失或不可用")

        parts.append(f"## 可用数据\n" + "\n".join(f"- {item}" for item in available))

        parts.append(
            f"\n请根据用户问题和对话上下文，判断需要执行哪种分析，"
            f"然后调用对应工具。如无法判断意图请直接追问。"
        )

        return "\n\n".join(parts)

    # ── 核心方法 ──

    def handle_single_stock(
        self,
        code: str,
        user_message: str = "",
        memory_context: str = "",
        chat_history: list[dict] | None = None,
        stock_data: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """使用显式股票数据分析单只股票。

        通过 ReAct Agent 自主决策执行基本面分析、技术面分析或两者。
        结果发布回共享内存。

        Args:
            code: 6位A股代码
            user_message: 当前轮用户原始输入（可空，回退为默认提示）
            memory_context: 近期对话摘要等记忆上下文
            chat_history: 原始对话历史（预留）
            stock_data: 按股票代码索引的 quote/basic_info/indicators/history 数据

        Returns:
            结构化分析结果 dict（含可选 technical_analysis 字段）
        """
        data_map = stock_data if isinstance(stock_data, dict) else {}
        item = data_map.get(code, {})
        indicators = item.get("indicators", {}) if isinstance(item, dict) else {}
        basic_info = item.get("basic_info", {}) if isinstance(item, dict) else {}
        history = item.get("history", {}) if isinstance(item, dict) else {}

        # 构建上下文
        context = self._build_analysis_context(
            code, indicators, basic_info, history,
            user_message, memory_context,
        )

        # ReAct Agent 执行
        try:
            result = self.agent.invoke(
                {"messages": [{"role": "user", "content": context}]},
                config={
                    "configurable": {
                        "thread_id": f"stock_analysis_{code}",
                    },
                },
            )
            messages = result.get("messages", [])
            final_response = (
                messages[-1].content if messages else "分析未能生成结果。"
            )
        except Exception as exc:
            # 降级：仅基本面分析
            return self._fallback_analyze(code, indicators, basic_info, item, str(exc))

        # 从消息中提取 tool 调用结果
        fundamental_json = None
        technical_json = None
        for msg in messages:
            if isinstance(msg, ToolMessage):
                content = str(msg.content).strip()
                if msg.name == "analyze_fundamentals":
                    parsed = safe_parse_json(content)
                    if isinstance(parsed, dict):
                        fundamental_json = parsed
                elif msg.name == "analyze_technicals":
                    parsed = safe_parse_json(content)
                    if isinstance(parsed, dict) and "error" not in parsed:
                        technical_json = parsed

        # 确定性兜底：若用户明确询问技术面指标（如 MACD/KDJ）但 ReAct Agent 未调用
        # analyze_technicals 工具，则直接调用工具计算，避免 LLM 漏调导致"无法给出分析"。
        tech_intent = _detect_technical_intent(user_message)
        if tech_intent and not technical_json:
            requested = [t for t in tech_intent if t] or None
            fallback_tech = self._direct_technical_analysis(code, requested, history)
            if fallback_tech is not None:
                technical_json = fallback_tech
                # 覆盖 ReAct Agent 的"无法分析"文本，改用工具结果解读
                final_response = self._summarize_technical_result(
                    fallback_tech, requested, basic_info, code,
                )

        # 构建返回 dict
        entry: Dict[str, Any] = {"code": code}

        if fundamental_json:
            entry.update(fundamental_json)
        else:
            # 没有调基本面工具时，填充默认值
            entry.setdefault("overall_score", 50)
            entry.setdefault("rating", "未分析")
            entry.setdefault("summary", final_response)

        # 合并技术面结果
        if technical_json:
            tech_summary = technical_json.pop("summary", {}) if isinstance(technical_json, dict) else {}
            if isinstance(tech_summary, dict):
                entry["technical_analysis"] = {
                    "overall_score": 50,  # 技术面不做评分，仅描述
                    "trend": tech_summary.get("trend", "震荡"),
                    "signals": tech_summary.get("signals", []),
                    "indicators": {
                        k: v for k, v in technical_json.items()
                        if k in {"MACD", "KDJ", "RSI", "BOLL", "MA", "WR"}
                    },
                    "summary": final_response,
                    "risks": tech_summary.get("risks", []),
                }
            else:
                entry["technical_analysis"] = technical_json

        # 确保 summary 有值
        if not entry.get("summary"):
            entry["summary"] = final_response

        # 补全展示用字段
        entry["name"] = basic_info.get("name", code) if isinstance(basic_info, dict) else code
        entry["indicators"] = indicators if isinstance(indicators, dict) else {}
        item = stock_item if isinstance(stock_item, dict) else {}
        quote = item.get("quote", {}) if isinstance(item, dict) else {}
        entry["quote"] = quote if isinstance(quote, dict) else {}
        candidate = item.get("search_candidate", {}) if isinstance(item, dict) else {}
        entry["search_candidate"] = candidate if isinstance(candidate, dict) else {}
        return entry

    def _direct_technical_analysis(
        self,
        code: str,
        indicators: list[str] | None,
        history: Dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """使用显式历史数据计算技术指标，作为确定性兜底。

        当 ReAct Agent 未调用 analyze_technicals 但用户明确询问技术面时使用。
        返回与 analyze_technicals 工具一致的 dict（含 summary），失败返回 None。
        """
        history = history or {}
        if not history or "error" in history:
            return None
        data_points = history.get("data")
        if not isinstance(data_points, list) or len(data_points) < 30:
            return None
        try:
            high = [float(d["high"]) for d in data_points]
            low = [float(d["low"]) for d in data_points]
            close = [float(d["close"]) for d in data_points]
        except (KeyError, ValueError, TypeError):
            return None
        try:
            return compute_all_indicators(high, low, close, indicators)
        except Exception:
            return None

    def _summarize_technical_result(
        self,
        tech_result: dict[str, Any],
        requested: list[str] | None,
        basic_info: Dict[str, Any],
        code: str,
    ) -> str:
        """根据技术指标计算结果生成简明文字解读，用于覆盖 ReAct 的"无法分析"回复。"""
        name = basic_info.get("name", code) if isinstance(basic_info, dict) else code
        summary_block = tech_result.get("summary", {}) if isinstance(tech_result, dict) else {}
        trend = summary_block.get("trend", "震荡") if isinstance(summary_block, dict) else "震荡"
        signals = summary_block.get("signals", []) if isinstance(summary_block, dict) else []
        risks = summary_block.get("risks", []) if isinstance(summary_block, dict) else []

        parts: list[str] = [f"已基于K线数据计算 {name}（{code}）的技术指标。"]
        parts.append(f"综合趋势：{trend}。")

        indicator_keys = requested or ["MACD", "KDJ", "RSI", "BOLL", "MA", "WR"]
        for key in indicator_keys:
            ind = tech_result.get(key) if isinstance(tech_result, dict) else None
            if not isinstance(ind, dict):
                continue
            if key == "MACD":
                latest = ind.get("latest", {})
                parts.append(
                    f"MACD：DIF {latest.get('DIF', '暂无')}，"
                    f"DEA {latest.get('DEA', '暂无')}，"
                    f"柱状线 {latest.get('histogram', '暂无')}；"
                    f"信号 {ind.get('signal') or '无明确信号'}，"
                    f"趋势 {ind.get('trend', '震荡')}"
                    + (f"，{ind.get('divergence')}" if ind.get("divergence") else "")
                )
            elif key == "KDJ":
                latest = ind.get("latest", {})
                parts.append(
                    f"KDJ：K {latest.get('K', '暂无')}，"
                    f"D {latest.get('D', '暂无')}，"
                    f"J {latest.get('J', '暂无')}；"
                    f"信号 {ind.get('signal') or '无明确信号'}，"
                    f"区间 {ind.get('zone', '正常')}"
                )
            elif key == "RSI":
                latest = ind.get("latest", {})
                zones = ind.get("zones", {}) or {}
                zone_desc = "、".join(f"{k}{v}" for k, v in zones.items()) or "正常"
                parts.append(
                    f"RSI：" + "，".join(f"{k}={v}" for k, v in latest.items()) + f"；区间 {zone_desc}"
                )
            elif key == "BOLL":
                latest = ind.get("latest", {})
                parts.append(
                    f"BOLL：MID {latest.get('MID', '暂无')}，"
                    f"UPPER {latest.get('UPPER', '暂无')}，"
                    f"LOWER {latest.get('LOWER', '暂无')}；"
                    f"带宽 {ind.get('bandwidth', '暂无')}，位置 {ind.get('position', '轨内')}"
                )
            elif key == "MA":
                latest = ind.get("latest", {})
                parts.append(
                    f"均线：" + "，".join(f"{k}={v}" for k, v in latest.items())
                    + f"；{ind.get('position', '')}"
                )
            elif key == "WR":
                latest = ind.get("latest", {})
                zones = ind.get("zones", {}) or {}
                zone_desc = "、".join(f"{k}{v}" for k, v in zones.items()) or "正常"
                parts.append(
                    f"WR：" + "，".join(f"{k}={v}" for k, v in latest.items()) + f"；区间 {zone_desc}"
                )

        if signals:
            parts.append("看多信号：" + "、".join(signals))
        if risks:
            parts.append("风险信号：" + "、".join(risks))

        return " ".join(parts)

    def _fallback_analyze(
        self,
        code: str,
        indicators: Dict[str, Any],
        basic_info: Dict[str, Any],
        stock_item: Dict[str, Any] | None = None,
        error_msg: str = "",
    ) -> Dict[str, Any]:
        """ReAct Agent 执行失败时降级为仅基本面分析。"""
        if not indicators and not basic_info:
            result = {
                "code": code, "rating": "未知", "overall_score": 50,
                "summary": f"分析执行异常{'：' + error_msg if error_msg else ''}",
            }
        else:
            financial_data = {
                "code": code,
                "basic_info": basic_info or {},
                "indicators": indicators or {},
            }
            raw = self._run_fundamental_chain(code, financial_data)
            parsed = safe_parse_json(raw)
            result = parsed if isinstance(parsed, dict) else {
                "code": code, "overall_score": 50, "rating": "中性",
                "summary": "基本面分析解析失败",
            }

        result["code"] = code
        result["overall_score"] = _safe_score(result.get("overall_score"))
        result["name"] = basic_info.get("name", code) if isinstance(basic_info, dict) else code
        result["indicators"] = indicators if isinstance(indicators, dict) else {}
        item = stock_item if isinstance(stock_item, dict) else {}
        quote = item.get("quote", {}) if isinstance(item, dict) else {}
        result["quote"] = quote if isinstance(quote, dict) else {}
        candidate = item.get("search_candidate", {}) if isinstance(item, dict) else {}
        result["search_candidate"] = candidate if isinstance(candidate, dict) else {}
        return result

    def handle(
        self,
        message: str,
        customer_id: str = "",
        chat_history: List[Dict[str, str]] | None = None,
        thread_id: str | None = None,
        memory_context: str = "",
    ) -> str:
        """分析所有关注股票。"""
        import re

        stock_codes = re.findall(
            r"(?<!\d)(60\d{4}|00\d{4}|30\d{4}|68\d{4}|8\d{5}|4\d{5})(?!\d)",
            message,
        )

        if not stock_codes:
            return "未识别到需要分析的股票代码。"

        analyses: list[Dict[str, Any]] = [
            self.handle_single_stock(
                code,
                user_message=message,
                memory_context=memory_context,
                chat_history=chat_history,
            )
            for code in stock_codes[:5]
        ]

        parts = [f"已完成 {len(analyses)} 只股票的分析："]
        for a in analyses:
            code = a.get("code", "")
            rating = a.get("rating", "未知")
            score = _safe_score(a.get("overall_score"), 0.0)
            summary = a.get("summary", "")
            tech = a.get("technical_analysis")
            tech_hint = ""
            if isinstance(tech, dict):
                tech_trend = tech.get("trend", "")
                tech_signals = tech.get("signals", [])
                if tech_trend:
                    tech_hint = f" 技术面：{tech_trend}"
                if tech_signals:
                    tech_hint += f" 信号：{'、'.join(tech_signals[:3])}"
            parts.append(
                f"  - {code} 评级：{rating}（{score:.0f}分）"
                f"{tech_hint} | {summary}"
            )

        return "\n".join(parts)
