"""金融投顾多 Agent 系统。

核心特性:
- 6 Agent 流水线：监督者 → 画像抽取 → 股票识别 → 数据获取 → 基本面分析 → 资产配置 → 合规风控
- data_fetch 与 fundamental_analysis 使用 LangGraph Send API 按股票 fan-out 并行执行
- 股票识别采用 LLM 驱动（识别中文全称/简称/代码 → 返回 code/name/industry）
- SharedWorkingMemory 跨 Agent 信息共享（线程安全，支持并行节点）
- 三层记忆机制（长期画像、近期摘要、滑动窗口）
- 增量压缩上下文
- 合规规则预检 + LLM 深度审查

工作流:
  START → supervisor → slot_extraction（画像与股票识别）
       → [data_fetch_single(code) × N 并行] → data_fetch_join
       → [fundamental_single(code) × N 并行] → fundamental_join
       → asset_allocation → compliance → final_snapshot → END
"""

from __future__ import annotations

import asyncio
import operator
import re
import threading
from typing import Any, Callable, Dict, List

from typing_extensions import Annotated, TypedDict

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send

from finance_agent.config import model
from finance_agent.core.shared_state import SharedWorkingMemory
from finance_agent.core.memory import AgentMemoryContext, RedisMemoryStore
from finance_agent.agents.supervisor import SupervisorAgent, needs_investment_profile
from finance_agent.agents.profile_extraction import SlotExtractionAgent
from finance_agent.agents.data_fetch import DataFetchAgent
from finance_agent.agents.fundamental_analysis import FundamentalAnalysisAgent
from finance_agent.agents.asset_allocation import AssetAllocationAgent
from finance_agent.agents.compliance import ComplianceAgent
from finance_agent.tools.qianfan_search import QianfanSearchError, QianfanStockSearch


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convert nullable external/LLM numeric values without aborting a workflow."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ── State ──────────────────────────────────────────────────────

class AdvisorState(TypedDict):
    user_message: str
    compressed_context: str
    effective_message: str
    chat_history: List[Dict[str, str]]
    customer_id: str
    task_plan: List[str]              # 任务分解结果
    missing_info: List[str]           # 建议继续向用户确认的信息
    user_profile: Dict[str, Any]      # 抽取的用户画像
    resolved_stocks: List[Dict[str, Any]]  # LLM 识别的股票列表（含 code/name/industry）
    candidate_stocks: List[Dict[str, Any]]  # 本轮行业筛选候选池
    stock_search_error: str
    stock_data: Dict[str, Any]        # 获取的金融数据（join 节点填充）
    fundamental_analysis: Dict[str, Any]   # 基本面分析结果（join 节点填充）
    allocation_result: Dict[str, Any]       # 资产配置结果
    agent_response: str               # 最终投顾回复
    compliance_result: Dict[str, Any]       # 合规审查结果
    memory_context: str
    shared_memory_snapshot: Dict[str, Any]
    thread_id: str
    contextual_follow_up: bool
    explicit_user_stock_codes: List[str]
    # ── 并行节点结果累积（使用 operator.add reducer 合并多 Send 分支）──
    stock_data_entries: Annotated[List[Dict[str, Any]], operator.add]
    fundamental_entries: Annotated[List[Dict[str, Any]], operator.add]


# ── 上下文压缩 ─────────────────────────────────────────────────

COMPRESS_PROMPT = """你是金融投顾系统的上下文压缩器。
请将历史对话压缩为下一轮判断所需的最小上下文，不要回答用户问题。

保留信息：
- 用户投资需求、约束、金额、期限、风险偏好、股票代码
- 助手提出的待确认事项
- 话题切换信号
- 不编造信息

请输出简洁中文摘要，保持在300字以内。"""


INCREMENTAL_COMPRESS_PROMPT = """你是金融投顾系统的上下文压缩器。
请基于已有摘要和新一轮对话，增量更新上下文摘要，不要回答用户问题。

输出要求：
1. 将新对话中的需求、约束、金额、期限、风险偏好、股票代码等信息合并到已有摘要
2. 保留助手主动提出的待确认事项，已被用户回答的可移除
3. 保留最近的话题切换信号
4. 已过时信息可精简
5. 不编造信息，保持在300字以内"""


class ContextCompressor:
    """增量上下文压缩器。"""

    def __init__(self):
        self._full_prompt = ChatPromptTemplate.from_messages([
            ("system", COMPRESS_PROMPT),
            ("human", "历史对话：\n{history}\n\n当前用户输入：{message}\n\n请压缩上下文："),
        ])
        self._incr_prompt = ChatPromptTemplate.from_messages([
            ("system", INCREMENTAL_COMPRESS_PROMPT),
            ("human",
             "已有摘要：\n{cached}\n\n"
             "最新一轮对话：\n用户：{user_msg}\n助手：{assistant_msg}\n\n"
             "请输出更新后的摘要："),
        ])
        self._cache: str = ""

    def compress(self, chat_history: List[Dict[str, str]], message: str) -> str:
        if not chat_history:
            self._cache = ""
            return "无历史对话。"

        if len(chat_history) < 4:
            return "\n".join(
                f"{'用户' if item.get('role') == 'user' else '助手'}: "
                f"{str(item.get('content', ''))[:3000]}"
                for item in chat_history
                if item.get("role") in {"user", "assistant"}
            )

        history_text = "\n".join(
            f"{'用户' if item.get('role') == 'user' else '助手'}: "
            f"{str(item.get('content', ''))[:3000]}"
            for item in chat_history
            if item.get("role") in {"user", "assistant"}
        )
        chain = self._full_prompt | model | StrOutputParser()
        self._cache = chain.invoke({"history": history_text, "message": message})
        return self._cache

    def reset_cache(self) -> None:
        self._cache = ""


# ── 主编排系统 ────────────────────────────────────────────────

class AdvisorSystem:
    """金融投顾多 Agent 编排系统。"""

    def __init__(self):
        self.shared_memory = SharedWorkingMemory()
        self.memory = AgentMemoryContext(RedisMemoryStore())
        self.compressor = ContextCompressor()
        self.supervisor = SupervisorAgent(shared_memory=self.shared_memory)
        self.slot_agent = SlotExtractionAgent(shared_memory=self.shared_memory)
        self.data_fetch_agent = DataFetchAgent(shared_memory=self.shared_memory)
        self.fundamental_agent = FundamentalAnalysisAgent(shared_memory=self.shared_memory)
        self.allocation_agent = AssetAllocationAgent(shared_memory=self.shared_memory)
        self.compliance_agent = ComplianceAgent(shared_memory=self.shared_memory)
        self.stock_search = QianfanStockSearch()
        self._session_counter: Dict[str, int] = {}
        self._progress_context = threading.local()
        self._progress_callbacks: Dict[str, Callable[[str, str], None]] = {}
        self._progress_lock = threading.Lock()
        self._trace_lock = threading.Lock()
        self._trace_sequences: Dict[str, int] = {}
        self.graph = self._build_graph()

    def _emit_progress(self, stage: str, message: str, thread_id: str = "") -> None:
        callback = None
        if thread_id:
            with self._progress_lock:
                callback = self._progress_callbacks.get(thread_id)
        if callback is None:
            callback = getattr(self._progress_context, "callback", None)
        if callback:
            callback(stage, message)

    def _trace_agent(self, state: dict[str, Any], agent_name: str, detail: str = "") -> None:
        """Print the real Agent execution order to the backend terminal."""
        customer_id = str(state.get("customer_id", "UNKNOWN"))
        thread_id = str(state.get("thread_id", customer_id))
        with self._trace_lock:
            sequence = self._trace_sequences.get(thread_id, 0) + 1
            self._trace_sequences[thread_id] = sequence
            suffix = f" [{detail}]" if detail else ""
            print(
                f"[Agent Flow] {customer_id} | {thread_id} | "
                f"{sequence:02d} -> {agent_name}{suffix}",
                flush=True,
            )

    @staticmethod
    def _is_contextual_follow_up(message: str, history: List[Dict[str, str]]) -> bool:
        if not history:
            return False
        references = (
            "这只", "这两只", "这几只", "这些", "上述", "上面", "前面", "刚才",
            "它", "它们", "该股", "这些股票", "这组", "这个组合",
            "哪种方案", "哪个方案", "这种方案", "这些方案", "上述方案",
            "选哪个", "选择哪个", "如何选择", "怎么选", "怎样选", "哪个更",
            "哪一个更", "更适合", "哪种更", "两者", "三者", "方案一", "方案二",
            # 组合构建/配置类追问 — 用户已看过分析，想让系统配置组合
            "构建组合", "组组合", "建组合", "怎么组合", "如何组合",
            "怎样组合", "组合一下", "配一下", "配置一下", "调整组合",
            "分配", "仓位", "权重", "怎么配", "如何配", "怎么买",
        )
        if any(word in message for word in references):
            return True
        # Elliptical comparison/selection questions commonly omit both stock names
        # and explicit pronouns but still refer to the immediately preceding answer.
        selection_pattern = re.compile(
            r"(?:选|选择|比较|对比).{0,10}(?:哪|哪个|哪种|更适合|更好)|"
            r"(?:哪|哪个|哪种).{0,10}(?:选|选择|适合|更好)"
        )
        if selection_pattern.search(message):
            return True
        # Portfolio construction follow-ups: user asks to build/adjust/allocate
        # after seeing a stock analysis, without repeating stock names.
        portfolio_pattern = re.compile(
            r"(?:帮|给|为)(?:我|我们).{0,6}(?:构建|组成|搭配|组合|配置|分配|调整)",
        )
        return bool(portfolio_pattern.search(message))

    @staticmethod
    def _history_stock_codes(history: List[Dict[str, str]]) -> List[str]:
        """Extract the most recently discussed A-share codes from prior turns."""
        pattern = re.compile(
            r"(?<!\d)(60\d{4}|00\d{4}|30\d{4}|68\d{4}|8\d{5}|4\d{5})(?!\d)"
        )
        for item in reversed(history):
            codes = list(dict.fromkeys(pattern.findall(str(item.get("content", "")))))
            if codes:
                return codes[:5]
        return []

    @staticmethod
    def _format_chat_history(history: List[Dict[str, str]]) -> str:
        return "\n".join(
            f"{'用户' if item.get('role') == 'user' else '助手'}: "
            f"{str(item.get('content', ''))[:4000]}"
            for item in history[-6:]
            if item.get("role") in {"user", "assistant"}
        )

    def _synthesize_response(self, state: AdvisorState) -> str:
        """Turn the verified draft into a direct answer to the user's actual question."""
        prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                "你是专业、审慎的金融分析助手，为机构投资者提供严谨的研究分析。"
                "请把系统生成的已验证数据底稿重新组织成对用户当前问题的直接回答，"
                "而不是照抄固定报告模板。先回应用户究竟想知道什么，再结合候选公司"
                "的业务关联、盈利、成长、估值、财务健康和风险说明为什么入选、"
                "彼此差异以及在什么条件下值得继续关注。结论要有取舍，不能只逐项罗列"
                "指标；数据缺失时明确说明其如何限制判断。不得虚构底稿外的数据、不得"
                "承诺收益、不得把研究候选说成确定买入建议。若底稿含来源链接，应保留"
                "与结论直接相关的链接。标题和措辞必须贴合用户提到的行业或主题。\n\n"
                "语言风格要求：使用正式、专业、客观的书面中文。不得使用\"挺不错\"、"
                "\"还不赖\"、\"可以的\"、\"还行\"、\"蛮好\"、\"OK\"等口语化或网络用语表述。"
                "不得使用\"咱们\"、\"啦\"、\"哦\"、\"哈\"等随意用语。指标评价使用\"优秀/良好/"
                "一般/需关注\"等专业评级术语。仅输出最终中文回复。",
            ),
            (
                "human",
                "历史对话：\n{history}\n\n当前问题：{message}\n\n"
                "本轮已验证的数据底稿：\n{draft}\n\n"
                "请围绕当前问题给出综合回答，不要复刻底稿的固定章节顺序：",
            ),
        ])
        chain = prompt | model | StrOutputParser()
        return chain.invoke({
            "history": self._format_chat_history(state.get("chat_history", [])),
            (
                "human",
                "历史对话：\n{history}\n\n当前问题：{message}\n\n"
                "本轮已验证的数据底稿：\n{draft}\n\n"
                "请围绕当前问题给出综合回答，不要复刻底稿的固定章节顺序：",
            ),
        ])
        chain = prompt | model | StrOutputParser()
        return chain.invoke({
            "history": self._format_chat_history(state.get("chat_history", [])),
            "message": state["user_message"],
            "draft": state.get("agent_response", "")[:12000],
        }).strip()

    def _build_fundamental_summary(
        self, analysis: Dict[str, Any], codes: List[str], screening: bool = False
    ) -> str:
        """根据基本面分析结果生成摘要回复（跳过 asset_allocation 时使用）。"""
        def metric(value: Any, suffix: str = "") -> str:
            if value is None or value == "":
                return "暂无"
            try:
                return f"{float(value):.2f}{suffix}"
            except (TypeError, ValueError):
                return "暂无"

        if not analysis:
            return (
                "未识别到股票代码或无可用基本面数据。"
                "请提供A股代码（如600519、000001）以便进行分析。"
            )

        title = "## 候选股票基本面对比" if screening else "## 基本面分析报告"
        parts = [title, ""]
        if screening:
            parts.extend([
                "以下标的是用于进一步研究的候选池，不代表确定值得买入。"
                "排序与取舍还需结合风险偏好、估值、持有期限和组合约束。",
                "",
            ])
        for code in codes:
            a = analysis.get(code, {})
            if not a:
                parts.append(f"- **{code}**：无可用数据")
                continue

            name = a.get("name", code)
            rating = a.get("rating", "未知")
            score = _safe_float(a.get("overall_score"))
            summary = a.get("summary", "")
            advantages = a.get("advantages", [])
            risks = a.get("risks", [])
            data = a.get("indicators", {}) or {}
            quote = a.get("quote", {}) or {}
            candidate = a.get("search_candidate", {}) or {}

            parts.append(f"### {code}「{name}」")
            parts.append(f"- **评级**：{rating}（{score:.0f}分）")
            if candidate:
                parts.append(f"- **搜索入选依据**：{candidate.get('reason') or '暂无'}")
                urls = candidate.get("source_urls", []) or []
                if urls:
                    parts.append("- **搜索来源**：" + "；".join(urls[:3]))
            parts.append(
                f"- **数据日期**：财务报告期 {data.get('date') or '暂无'}；"
                f"行情日期 {quote.get('date') or '暂无'}"
            )
            if quote and "error" not in quote:
                parts.append(
                    f"- **行情数据**：收盘价 {metric(quote.get('price'), ' 元')}；"
                    f"涨跌幅 {metric(quote.get('change_pct'), '%')}；"
                    f"PE(TTM) {metric(quote.get('pe'))}；PB {metric(quote.get('pb'))}"
                )
            if data and "error" not in data:
                parts.append(
                    f"- **盈利指标**：ROE {metric(data.get('roe'), '%')}；"
                    f"净利率 {metric(data.get('net_profit_margin'), '%')}；"
                    f"毛利率 {metric(data.get('gross_margin'), '%')}；"
                    f"EPS(TTM) {metric(data.get('eps'), ' 元')}"
                )
                parts.append(
                    f"- **成长与偿债**：营收同比 {metric(data.get('revenue_growth'), '%')}；"
                    f"净利润同比 {metric(data.get('net_profit_growth'), '%')}；"
                    f"总资产同比 {metric(data.get('total_asset_growth'), '%')}；"
                    f"资产负债率 {metric(data.get('debt_ratio'), '%')}；"
                    f"流动比率 {metric(data.get('current_ratio'))}"
                )
            parts.append(f"- **总结**：{summary}")
            if advantages:
                parts.append(f"- **优势**：{'；'.join(advantages)}")
            if risks:
                parts.append(f"- **风险**：{'；'.join(risks)}")
            parts.append("")

        parts.append("### 风险提示")
        parts.append(
            "以上分析基于公开财务数据，仅供研究参考，不构成投资建议。"
            "投资有风险，过往业绩不代表未来收益，请谨慎决策。"
        )
        return "\n".join(parts)

    def _build_graph(self) -> CompiledStateGraph:

        # ── 节点 1: 监督者（选择需要执行的子 Agent）──
        def supervisor_handler(state: AdvisorState) -> AdvisorState:
            self._trace_agent(state, "SupervisorAgent")
            self._emit_progress("supervisor", "正在判断需要执行的分析步骤")
            state["contextual_follow_up"] = self._is_contextual_follow_up(
                state["user_message"], state.get("chat_history", [])
            )
            result = self.supervisor.plan_tasks(
                state["user_message"],
                state.get("compressed_context", "") or state.get("memory_context", ""),
            )
            state["task_plan"] = result["task_plan"]
            state["missing_info"] = result.get("missing_info", [])
            print(
                f"[Agent Plan] {state['customer_id']} | {state['thread_id']} | "
                + " -> ".join(result["task_plan"]),
                flush=True,
            )
            return state

        # ── 节点 2: 关键信息槽位提取（画像 + 股票识别）──
        def slot_extraction_handler(state: AdvisorState) -> AdvisorState:
            self._trace_agent(state, "SlotExtractionAgent")
            self._emit_progress("slot_extraction", "正在提取画像与股票等关键信息")
            """用 LLM 识别用户消息中的股票名称，返回代码+名称+行业。

            统一提取画像与股票槽位；明确代码可直接走确定性解析。
            """
            message = state["user_message"]
            slots = self.slot_agent.extract_slots(message, state.get("user_profile", {}) or {})
            user_profile = slots["user_profile"]
            state["user_profile"] = user_profile
            explicit = slots["resolved_stocks"]
            detected = explicit
            # 只把当前输入中确实出现的名称/代码视为明确标的，防止模型把行业扩展成股票。
            resolved = list(explicit)
            explicit_codes = re.findall(
                r"(?<!\d)(60\d{4}|00\d{4}|30\d{4}|68\d{4}|8\d{5}|4\d{5})(?!\d)",
                message,
            )
            for stock in ([] if explicit else detected):
                code = stock.get("code", "")
                name = stock.get("name", "")
                explicit_name = bool(name and (name in message or (len(name) >= 4 and name[-2:] in message)))
                if code in message or explicit_name:
                    resolved.append(stock)
            detected_codes = {stock.get("code") for stock in resolved}
            for code in explicit_codes:
                if code not in detected_codes:
                    resolved.append({"code": code, "name": "", "industry": ""})

            # Only stocks explicitly named or coded in the current message may be
            # persisted to the user's watchlist. Search candidates stay turn-local.
            state["explicit_user_stock_codes"] = list(dict.fromkeys(
                stock.get("code", "") for stock in resolved if stock.get("code")
            ))

            # “这两只/上述股票”等追问沿用最近一轮标的，不能重新做主题搜索。
            if not resolved and state.get("contextual_follow_up"):
                history_codes = self._history_stock_codes(state.get("chat_history", []))
                profile_codes = user_profile.get("stock_codes", []) if isinstance(user_profile, dict) else []
                for code in history_codes or profile_codes:
                    basic = self.shared_memory.query(f"stock_basic_info_{code}", {}) or {}
                    resolved.append({
                        "code": code,
                        "name": str(basic.get("name", "")),
                        "industry": str(basic.get("industry", "")),
                    })

            if (not resolved and not state.get("contextual_follow_up")
                    and "data_fetch" in (state.get("task_plan", []) or [])):
                try:
                    self._emit_progress("stock_search", "正在搜索相关行业的A股候选")
                    searched = self.stock_search.search(message)
                    # 搜索工具已经校验代码格式和资料来源。不要在这里再串行登录
                    # BaoStock 做身份校验：BaoStock SDK 没有请求超时，连接异常会
                    # 永久占有全局 session 锁。名称以随后 data_fetch 获取的
                    # basic_info 为最终权威值。
                    resolved = searched
                    state["candidate_stocks"] = searched
                    self._emit_progress("stock_validation", "候选代码已确认，准备获取权威证券信息")
                except QianfanSearchError as exc:
                    state["stock_search_error"] = str(exc)
                    resolved = []

            # 当前问题没有明确股票且搜索失败时清空旧标的，绝不回退到历史股票。
            if not resolved and isinstance(user_profile, dict):
                user_profile["stock_codes"] = []
                state["user_profile"] = user_profile
                self.shared_memory.publish_fact("user_profile", user_profile, source="slot_extraction")
            if resolved:
                codes = list(dict.fromkeys(s["code"] for s in resolved))
                if isinstance(user_profile, dict):
                    user_profile["stock_codes"] = codes
                    state["user_profile"] = user_profile
                    self.shared_memory.publish_fact(
                        "user_profile", user_profile, source="slot_extraction"
                    )

            state["resolved_stocks"] = resolved

            # 把每只股票的基本识别信息写入共享内存（供下游展示）
            for s in resolved:
                if self.shared_memory and s.get("name"):
                    self.shared_memory.publish_fact(
                        f"stock_basic_info_{s['code']}",
                        {"code": s["code"], "name": s["name"], "industry": s.get("industry", "")},
                        source="slot_extraction",
                    )
                if s.get("source") == "baidu_qianfan_search":
                    self.shared_memory.publish_fact(
                        f"stock_search_candidate_{s['code']}", s, source="baidu_qianfan_search"
                    )

            if "data_fetch" not in (state.get("task_plan", []) or []):
                state["agent_response"] = self.slot_agent.handle(message)
            return state

        # ── 节点 4: 金融数据获取（Send fan-out 按股票并行）──

        def _resolve_stock_codes(state: AdvisorState) -> List[str]:
            """解析股票代码：优先 resolved_stocks，其次 user_profile，最后正则。"""
            # 1. 优先从 LLM 识别结果读取
            resolved = state.get("resolved_stocks", []) or []
            if resolved:
                return [s["code"] for s in resolved if s.get("code")][:5]
            # 2. 从 user_profile 读取
            user_profile = state.get("user_profile", {}) or {}
            if isinstance(user_profile, dict):
                codes = list(user_profile.get("stock_codes", []))
                if codes:
                    return codes[:5]
            # 3. 正则兜底
            codes = re.findall(
                r"(?<!\d)(60\d{4}|00\d{4}|30\d{4}|68\d{4}|8\d{5}|4\d{5})(?!\d)",
                state.get("user_message", ""),
            )
            return codes[:5]

        def route_data_fetch(state: AdvisorState):
            """fan-out 路由：为每只股票生成一个 Send 到 data_fetch_single。

            无股票代码时直接跳到 data_fetch_join（空 fan-out 边界处理）。
            """
            codes = _resolve_stock_codes(state)
            if not codes:
                return "data_fetch_join"
            trace_context = {
                "customer_id": state.get("customer_id", ""),
                "thread_id": state.get("thread_id", ""),
            }
            return [Send("data_fetch_single", {"code": c, **trace_context}) for c in codes]

        def route_after_slots(state: AdvisorState):
            if "data_fetch" not in (state.get("task_plan", []) or []):
                return "compliance"
            return route_data_fetch(state)

        def route_after_data_fetch(state: AdvisorState):
            if state.get("stock_search_error"):
                return "compliance"
            plan = state.get("task_plan", []) or []
            if "fundamental_analysis" in plan:
                return route_fundamental(state)
            if "asset_allocation" in plan:
                return "asset_allocation"
            return "compliance"

        def data_fetch_single_handler(state: dict) -> dict:
            """单股票并行节点：调用 agent.handle_single_stock 写入共享内存。"""
            code = state["code"]
            self._trace_agent(state, "DataFetchAgent", code)
            self._emit_progress(
                "data_fetch", f"正在获取 {code} 的行情与财务数据",
                str(state.get("thread_id", "")),
            )
            entry = self.data_fetch_agent.handle_single_stock(code)
            # 通过 operator.add reducer 累积到 stock_data_entries
            return {"stock_data_entries": [entry]}

        def data_fetch_join_handler(state: AdvisorState) -> AdvisorState:
            """join 节点：所有并行 data_fetch_single 完成后，从共享内存收集数据。"""
            stock_data: Dict[str, Any] = {}
            user_profile = state.get("user_profile", {}) or {}
            codes = user_profile.get("stock_codes", []) if isinstance(user_profile, dict) else []
            if not codes:
                # 回退：从累积的 entries 提取
                codes = [e.get("code") for e in state.get("stock_data_entries", []) if e.get("code")]
            for code in codes:
                stock_data[code] = {
                    "quote": self.shared_memory.query(f"stock_quote_{code}", {}),
                    "indicators": self.shared_memory.query(f"financial_indicator_{code}", {}),
                    "basic_info": self.shared_memory.query(f"stock_basic_info_{code}", {}),
                    "history": self.shared_memory.query(f"stock_history_{code}", {}),
                }
            state["stock_data"] = stock_data
            if state.get("stock_search_error"):
                state["agent_response"] = (
                    "无法确定需要分析的股票候选：" + state["stock_search_error"]
                    + "。请配置百度千帆搜索 API，或直接提供股票名称/代码。"
                )
                return state
            if "fundamental_analysis" not in (state.get("task_plan", []) or []):
                lines = ["## 股票数据"]
                for code, item in stock_data.items():
                    basic = item.get("basic_info", {}) or {}
                    quote = item.get("quote", {}) or {}
                    lines.append(
                        f"- {code}「{basic.get('name', '')}」："
                        f"{quote.get('date') or '暂无'} 收盘 {_safe_float(quote.get('price')):.2f} 元，"
                        f"涨跌幅 {_safe_float(quote.get('change_pct')):+.2f}%"
                    )
                lines.append("\n投资有风险，过往业绩不代表未来收益，请谨慎决策。")
                state["agent_response"] = "\n".join(lines)
            return state

        # ── 节点 4: 基本面分析（Send fan-out 按股票并行）──

        def route_fundamental(state: AdvisorState):
            """fan-out 路由：为每只股票生成一个 Send 到 fundamental_single。"""
            codes = _resolve_stock_codes(state)
            if not codes:
                return "fundamental_join"
            trace_context = {
                "customer_id": state.get("customer_id", ""),
                "thread_id": state.get("thread_id", ""),
            }
            return [Send("fundamental_single", {"code": c, **trace_context}) for c in codes]

        def fundamental_single_handler(state: dict) -> dict:
            """单股票并行节点：调用 agent.handle_single_stock 进行 LLM 分析。"""
            code = state["code"]
            self._trace_agent(state, "FundamentalAnalysisAgent", code)
            self._emit_progress(
                "fundamental_analysis", f"正在分析 {code} 的基本面",
                str(state.get("thread_id", "")),
            )
            entry = self.fundamental_agent.handle_single_stock(code)
            return {"fundamental_entries": [entry]}

        def fundamental_join_handler(state: AdvisorState) -> AdvisorState:
            """join 节点：从共享内存收集所有基本面分析结果。

            当 task_plan 不包含 asset_allocation 时，同时生成基本面摘要回复。
            """
            analysis: Dict[str, Any] = {}
            user_profile = state.get("user_profile", {}) or {}
            codes = user_profile.get("stock_codes", []) if isinstance(user_profile, dict) else []
            if not codes:
                codes = [e.get("code") for e in state.get("fundamental_entries", []) if e.get("code")]
            for code in codes:
                result = self.shared_memory.query(f"fundamental_analysis_{code}", {})
                if result:
                    analysis[code] = result
            state["fundamental_analysis"] = analysis

            # 条件路由：task_plan 不含 asset_allocation 或股票数 < 2 时，生成基本面摘要回复
            task_plan = state.get("task_plan", []) or []
            if "asset_allocation" not in task_plan or len(codes) < 2:
                state["agent_response"] = self._build_fundamental_summary(
                    analysis, codes, screening=bool(state.get("candidate_stocks"))
                )

            return state

        def route_after_fundamental(state: AdvisorState) -> str:
            """条件路由：根据 task_plan 与实际股票数量决定是否执行 asset_allocation。

            - 股票数 < 2 → 跳过 asset_allocation，走 compliance
            - task_plan 包含 "asset_allocation" 且股票数 >= 2 → 执行 asset_allocation
            - task_plan 不包含 → 跳过到 compliance
            - task_plan 缺失或异常 → 默认执行 asset_allocation（仅当股票数 >= 2）
            """
            codes = _resolve_stock_codes(state)
            if len(codes) < 2:
                return "compliance"

            task_plan = state.get("task_plan", []) or []
            if isinstance(task_plan, list) and "asset_allocation" in task_plan:
                return "asset_allocation"
            if isinstance(task_plan, list) and len(task_plan) > 0:
                # task_plan 非空但不包含 asset_allocation → 跳过
                return "compliance"
            # task_plan 缺失或空 → 默认执行 asset_allocation（向后兼容）
            return "asset_allocation"

        # ── 节点 5: 资产配置 ──
        def asset_allocation_handler(state: AdvisorState) -> AdvisorState:
            self._trace_agent(state, "AssetAllocationAgent")
            self._emit_progress("asset_allocation", "正在计算资产配置方案")
            # 健壮性保障：确保 shared_memory 的 user_profile.stock_codes 与 state 一致
            user_profile = state.get("user_profile", {}) or {}
            resolved_stocks = state.get("resolved_stocks", []) or []
            if isinstance(user_profile, dict) and resolved_stocks:
                codes = [s.get("code") for s in resolved_stocks if isinstance(s, dict) and s.get("code")]
                if codes and list(user_profile.get("stock_codes", [])) != codes:
                    user_profile["stock_codes"] = codes
                    state["user_profile"] = user_profile
                    self.shared_memory.publish_fact(
                        "user_profile", user_profile, source="asset_allocation_sync"
                    )

            response = self.allocation_agent.handle(
                state["user_message"],
                state.get("compressed_context", ""),
                state["customer_id"],
                state.get("chat_history", []),
                state.get("thread_id"),
                state.get("memory_context", ""),
            )
            state["agent_response"] = response
            state["allocation_result"] = self.shared_memory.query("allocation_result", {}) or {}
            return state

        # ── 节点 6: 合规风控审查 ──
        def compliance_handler(state: AdvisorState) -> AdvisorState:
            self._trace_agent(state, "ComplianceAgent")
            self._emit_progress("compliance", "正在检查回复并整理补充建议")
            has_verified_analysis = bool(
                state.get("fundamental_analysis")
                or state.get("allocation_result")
                or state.get("stock_data")
            )
            if (
                has_verified_analysis
                and state.get("agent_response")
                and not state.get("stock_search_error")
            ):
                try:
                    state["agent_response"] = self._synthesize_response(state)
                except Exception:
                    # Keep the verified deterministic draft if final synthesis fails.
                    pass
            profile = state.get("user_profile", {}) or {}
            field_aliases = {"budget": "budget_amount"}
            missing_info = []
            requested_missing = (
                state.get("missing_info", [])
                if (
                    needs_investment_profile(state.get("user_message", ""))
                    and not state.get("stock_search_error")
                )
                else []
            )
            for field in requested_missing:
                profile_field = field_aliases.get(field, field)
                if not isinstance(profile, dict) or not profile.get(profile_field):
                    missing_info.append(field)
            result = self.compliance_agent.review(
                agent_response=state["agent_response"],
                missing_info=missing_info,
            )
            state["compliance_result"] = result

            # 合规不通过 → 附加合规提示到回复（保留用户体验，移除升级人工标记）
            if not result.get("pass", True):
                state["agent_response"] = (
                    state["agent_response"]
                    + "\n\n---\n⚠️ 合规提示："
                    + result.get("reason", "回复中存在敏感表述，请修改后参考。")
                )

            questions = result.get("follow_up_questions", [])
            if questions:
                state["agent_response"] += "\n\n### 为了进一步完善分析，请补充\n" + "\n".join(
                    f"- {question}" for question in questions
                )

            return state

        def final_snapshot(state: AdvisorState) -> AdvisorState:
            state["shared_memory_snapshot"] = self.shared_memory.snapshot()
            return state

        # ── 构建图 ─────────────────────────────────────────
        # START → supervisor → slot_extraction（画像与股票识别）
        #       → [data_fetch_single × N 并行] → data_fetch_join
        #       → [fundamental_single × N 并行] → fundamental_join
        #       → route_after_fundamental ─┬─ asset_allocation → compliance
        #                                └──────────────────→ compliance
        #       → final_snapshot → END

        graph = StateGraph(AdvisorState)

        graph.add_node("supervisor", supervisor_handler)
        graph.add_node("slot_extraction", slot_extraction_handler)

        # data_fetch fan-out 拆分
        graph.add_node("data_fetch_single", data_fetch_single_handler)
        graph.add_node("data_fetch_join", data_fetch_join_handler)

        # fundamental fan-out 拆分
        graph.add_node("fundamental_single", fundamental_single_handler)
        graph.add_node("fundamental_join", fundamental_join_handler)

        graph.add_node("asset_allocation", asset_allocation_handler)
        graph.add_node("compliance", compliance_handler)
        graph.add_node("final_snapshot", final_snapshot)

        # 边：顺序段
        graph.add_edge(START, "supervisor")
        graph.add_edge("supervisor", "slot_extraction")
        graph.add_conditional_edges(
            "slot_extraction",
            route_after_slots,
            ["data_fetch_single", "data_fetch_join", "compliance"],
        )
        # 所有 data_fetch_single 收敛到 data_fetch_join
        graph.add_edge("data_fetch_single", "data_fetch_join")

        # data_fetch_join 根据 task_plan 决定是否继续基本面、配置或合规
        graph.add_conditional_edges(
            "data_fetch_join",
            route_after_data_fetch,
            ["fundamental_single", "fundamental_join", "asset_allocation", "compliance"],
        )
        # 所有 fundamental_single 收敛到 fundamental_join
        graph.add_edge("fundamental_single", "fundamental_join")

        # 顺序下游段
        # 条件路由：根据 task_plan 决定是否执行 asset_allocation
        graph.add_conditional_edges(
            "fundamental_join",
            route_after_fundamental,
            ["asset_allocation", "compliance"],
        )
        graph.add_edge("asset_allocation", "compliance")
        graph.add_edge("compliance", "final_snapshot")
        graph.add_edge("final_snapshot", END)

        return graph.compile()

    # ── 公共 API ─────────────────────────────────────────────

    def handle_message(
        self,
        message: str,
        chat_history: List[Dict[str, str]] | None = None,
        customer_id: str = "CUST001",
        progress_callback: Callable[[str, str], None] | None = None,
        conversation_id: str = "",
    ) -> Dict[str, Any]:
        """处理用户消息，返回投顾回复。"""
        self._progress_context.callback = progress_callback
        self._emit_progress("preparing", "正在准备分析上下文")
        database = self.memory.database
        conversation = database.get_conversation(conversation_id, customer_id) if conversation_id else None
        if not conversation:
            conversation = database.create_conversation(customer_id)
            conversation_id = conversation["conversation_id"]
            # Synchronize messages already visible in the client when adopting a new session.
            for item in chat_history or []:
                role = "user" if item.get("role") == "user" else "assistant"
                content = str(item.get("content", "")).strip()
                if content:
                    database.append_conversation_message(conversation_id, role, content)
        thread_id = conversation_id
        if progress_callback:
            with self._progress_lock:
                self._progress_callbacks[thread_id] = progress_callback
        fallback_history = chat_history or []
        memory_data = self.memory.load_context(customer_id, conversation_id, fallback_history)
        self.memory.append_window_message(conversation_id, "user", message)
        effective_history = memory_data.get("sliding_window") or fallback_history[-5:]

        # 上下文压缩
        compressed = self.compressor.compress(effective_history, message)

        initial_state: AdvisorState = {
            "user_message": message,
            "compressed_context": compressed,
            "effective_message": message,
            "chat_history": effective_history,
            "customer_id": customer_id,
            "task_plan": [],
            "missing_info": [],
            "user_profile": memory_data.get("profile", {}) or {},
            "resolved_stocks": [],
            "candidate_stocks": [],
            "stock_search_error": "",
            "stock_data": {},
            "fundamental_analysis": {},
            "allocation_result": {},
            "agent_response": "",
            "compliance_result": {},
            "memory_context": memory_data.get("context_text", ""),
            "shared_memory_snapshot": {},
            "thread_id": thread_id,
            "contextual_follow_up": False,
            "explicit_user_stock_codes": [],
            "stock_data_entries": [],
            "fundamental_entries": [],
        }

        with self._trace_lock:
            self._trace_sequences[thread_id] = 0
        try:
            result = self.graph.invoke(initial_state)
        finally:
            self._progress_context.callback = None
            with self._progress_lock:
                self._progress_callbacks.pop(thread_id, None)
            with self._trace_lock:
                self._trace_sequences.pop(thread_id, None)

        output = {
            "response": result["agent_response"],
            "task_plan": result["task_plan"],
            "user_profile": result.get("user_profile", {}),
            "stock_data": result.get("stock_data", {}),
            "fundamental_analysis": result.get("fundamental_analysis", {}),
            "allocation_result": result.get("allocation_result", {}),
            "compliance_result": result.get("compliance_result", {}),
            "shared_memory_snapshot": result.get("shared_memory_snapshot", {}),
            "explicit_user_stock_codes": result.get("explicit_user_stock_codes", []),
            "conversation_id": conversation_id,
        }

        # 更新记忆（按对话隔离）
        database.rename_conversation_from_message(conversation_id, message)
        database.append_conversation_message(conversation_id, "user", message)
        database.append_conversation_message(
            conversation_id, "assistant", output["response"], {"task_plan": output["task_plan"]},
        )
        self.memory.append_window_message(
            conversation_id, "assistant", output["response"],
            {"task_plan": output["task_plan"]},
        )
        self.memory.update_profile_from_result(customer_id, message, output)
        self.memory.update_recent_summary(
            conversation_id,
            fallback_history + [
                {"role": "user", "content": message},
                {"role": "assistant", "content": output["response"], "metadata": output},
            ],
            compressed if compressed != "无历史对话。" else "",
        )

        return output

    async def handle_message_stream(
        self,
        message: str,
        chat_history: List[Dict[str, str]] | None = None,
        customer_id: str = "CUST001",
        conversation_id: str = "",
    ):
        """流式处理消息，逐事件返回。"""
        # 发送阶段事件
        yield {"type": "stage", "stage": "supervisor", "message": "正在选择需要执行的子 Agent..."}
        # 完整分析包含同步模型/数据源调用，放入工作线程，避免阻塞 FastAPI 事件循环。
        loop = asyncio.get_running_loop()
        progress_queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()

        def report(stage: str, text: str) -> None:
            loop.call_soon_threadsafe(
                progress_queue.put_nowait,
                {"type": "stage", "stage": stage, "message": text},
            )

        task = asyncio.create_task(asyncio.to_thread(
            self.handle_message, message, chat_history, customer_id, report, conversation_id
        ))
        heartbeat_elapsed = 0.0
        while not task.done() or not progress_queue.empty():
            try:
                yield await asyncio.wait_for(progress_queue.get(), timeout=1.0)
                heartbeat_elapsed = 0.0
            except asyncio.TimeoutError:
                heartbeat_elapsed += 1.0
                if heartbeat_elapsed >= 15.0:
                    # 保持 SSE 连接活跃，避免代理或浏览器把长耗时分析误判为超时。
                    yield {"type": "heartbeat"}
                    heartbeat_elapsed = 0.0
        result = await task

        # 发送最终回复
        yield {"type": "response", "content": result["response"], "data": result}

    def reset_session(self, customer_id: str = "") -> None:
        self.shared_memory.reset()
        self.compressor.reset_cache()
        if customer_id:
            self._session_counter[customer_id] = self._session_counter.get(customer_id, 0) + 1

    def get_shared_memory_snapshot(self) -> Dict[str, Any]:
        return self.shared_memory.snapshot()

    def get_user_profile(self, customer_id: str) -> Dict[str, Any]:
        """获取用户画像。"""
        from dataclasses import asdict
        profile = self.memory.get_profile(customer_id)
        return asdict(profile)
