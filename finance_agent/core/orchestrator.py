"""金融投顾多 Agent 系统。

核心特性:
- 6 Agent 流水线：监督者 → 画像抽取 → 数据获取 → 股票分析 → 资产配置 → 合规风控
- data_fetch 与 stock_analysis 使用 LangGraph @task 按股票 fan-out 并行执行
- 股票识别采用 LLM 驱动（识别中文全称/简称/代码 → 返回 code/name/industry）
- SharedWorkingMemory 跨 Agent 信息共享（线程安全，支持并行节点）
- 三层记忆机制（长期画像、近期摘要、滑动窗口）
- 增量压缩上下文
- 合规规则预检 + LLM 深度审查

工作流:
  START → supervisor → slot_extraction（画像与股票识别）
       → data_fetch_batch（@task × N 并行）
       → stock_analysis_batch（@task × N 并行）
       → asset_allocation → compliance → final_snapshot → END
"""

from __future__ import annotations

import asyncio
import queue
import re
import threading
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List

from typing_extensions import TypedDict

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langgraph.func import task
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from finance_agent.config import (
    FINAL_SYNTHESIS_TIMEOUT,
    get_checkpoint_saver,
    get_model_for_agent,
)
from finance_agent.core.shared_state import SharedWorkingMemory
from finance_agent.core.memory import AgentMemoryContext, RedisMemoryStore
from finance_agent.agents.supervisor import (
    SupervisorAgent,
    requires_slot_extraction,
)
from finance_agent.tools.finance_slots import (
    FinanceSlotsExtractor,
    create_extract_finance_slots_tool,
)
from finance_agent.agents.data_fetch import DataFetchAgent
from finance_agent.agents.stock_analysis import StockAnalysisAgent
from finance_agent.agents.asset_allocation import AssetAllocationAgent
from finance_agent.agents.compliance import ComplianceAgent
from finance_agent.tools.web_search import WebSearchError, MarketSearch
from finance_agent.middleware import BLOCKED_RESPONSE, find_sensitive_word
from finance_agent.core.database import get_database


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convert nullable external/LLM numeric values without aborting a workflow."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _format_indicator_line(name: str, data: dict[str, Any]) -> str:
    """将单个技术指标结果格式化为单行展示文本。"""
    if not isinstance(data, dict):
        return ""
    latest = data.get("latest", {}) or {}
    if name == "MACD":
        sig = data.get("signal") or "无信号"
        trend = data.get("trend", "震荡")
        div = data.get("divergence") or ""
        return (
            f"DIF {latest.get('DIF', '暂无')}，DEA {latest.get('DEA', '暂无')}，"
            f"柱状线 {latest.get('histogram', '暂无')}；信号 {sig}，趋势 {trend}"
            + (f"，{div}" if div else "")
        )
    if name == "KDJ":
        sig = data.get("signal") or "无信号"
        zone = data.get("zone", "正常")
        return (
            f"K {latest.get('K', '暂无')}，D {latest.get('D', '暂无')}，"
            f"J {latest.get('J', '暂无')}；信号 {sig}，区间 {zone}"
        )
    if name == "RSI":
        zones = data.get("zones", {}) or {}
        zone_desc = "、".join(f"{k}{v}" for k, v in zones.items()) or "正常"
        vals = "，".join(f"{k}={v}" for k, v in latest.items())
        return f"{vals}；区间 {zone_desc}" if vals else ""
    if name == "BOLL":
        pos = data.get("position", "轨内")
        bw = data.get("bandwidth", "暂无")
        return (
            f"MID {latest.get('MID', '暂无')}，UPPER {latest.get('UPPER', '暂无')}，"
            f"LOWER {latest.get('LOWER', '暂无')}；带宽 {bw}，位置 {pos}"
        )
    if name == "MA":
        pos = data.get("position", "")
        vals = "，".join(f"{k}={v}" for k, v in latest.items())
        return (f"{vals}；{pos}").strip("；")
    if name == "WR":
        zones = data.get("zones", {}) or {}
        zone_desc = "、".join(f"{k}{v}" for k, v in zones.items()) or "正常"
        vals = "，".join(f"{k}={v}" for k, v in latest.items())
        return f"{vals}；区间 {zone_desc}" if vals else ""
    return ""


# ── State ──────────────────────────────────────────────────────

class AdvisorState(TypedDict):
    user_message: str
    chat_history: List[Dict[str, str]]
    customer_id: str
    task_plan: List[str]              # 任务分解结果
    business_state: Dict[str, Any]    # 业务 Agent 自维护的必填状态
    user_profile: Dict[str, Any]      # 抽取的用户画像
    resolved_stocks: List[Dict[str, Any]]  # LLM 识别的股票列表（含 code/name/industry）
    candidate_stocks: List[Dict[str, Any]]  # 本轮行业筛选候选池
    stock_search_error: str
    stock_resolution_error: str
    stock_data: Dict[str, Any]        # 获取的金融数据（join 节点填充）
    stock_analysis: Dict[str, Any]   # 股票综合分析结果（join 节点填充）
    technical_analysis: Dict[str, Any]   # 技术面分析结果
    allocation_result: Dict[str, Any]       # 资产配置结果
    agent_response: str               # 最终投顾回复
    compliance_result: Dict[str, Any]       # 合规审查结果
    memory_context: str
    intent_context: str
    shared_memory_snapshot: Dict[str, Any]
    thread_id: str
    run_id: str
    explicit_user_stock_codes: List[str]
    # 保留批处理明细字段以兼容 checkpoint 与调用方。
    stock_data_entries: List[Dict[str, Any]]
    stock_analysis_entries: List[Dict[str, Any]]
    detected_intents: List[Dict[str, Any]]
    intent_results: Dict[str, Dict[str, Any]]
    intent_source: str
    finance_related: bool
    intent_stocks: Dict[str, List[Dict[str, Any]]]
    slot_tool_calls: List[Dict[str, Any]]
    slot_tool_called: bool
    slot_tool_source: str
    slot_tool_error: str
    uncertain_intents: List[Dict[str, Any]]
    intent_clarification_state: Dict[str, Any]
    intent_clarification_response: str


# ── 主编排系统 ────────────────────────────────────────────────

class AdvisorSystem:
    """金融投顾多 Agent 编排系统。"""

    def __init__(self):
        self.shared_memory = SharedWorkingMemory()
        # 共享的 SqliteSaver，所有 Agent 子图和主编排图共用
        self.checkpointer = get_checkpoint_saver()
        self.memory = AgentMemoryContext(
            store=RedisMemoryStore(),
            checkpointer=self.checkpointer,
        )
        self.supervisor = SupervisorAgent(
            shared_memory=self.shared_memory, checkpointer=self.checkpointer,
        )
        self.finance_slots_extractor = FinanceSlotsExtractor()
        self.data_fetch_agent = DataFetchAgent(
            shared_memory=self.shared_memory, checkpointer=self.checkpointer,
        )
        self.stock_agent = StockAnalysisAgent(
            shared_memory=self.shared_memory, checkpointer=self.checkpointer,
        )
        self.allocation_agent = AssetAllocationAgent(
            shared_memory=self.shared_memory, checkpointer=self.checkpointer,
        )
        self.compliance_agent = ComplianceAgent(
            shared_memory=self.shared_memory, checkpointer=self.checkpointer,
        )
        self.stock_search = MarketSearch()
        self._session_counter: Dict[str, int] = {}
        self._progress_context = threading.local()
        self._progress_callbacks: Dict[str, Callable[[str, str], None]] = {}
        self._progress_lock = threading.Lock()
        self._trace_lock = threading.Lock()
        # SharedWorkingMemory is mutable and used by every Agent. Serialize a full
        # workflow until it is replaced by a conversation-scoped state backend.
        self._workflow_lock = threading.RLock()
        self._trace_sequences: Dict[str, int] = {}
        self.graph = self._build_graph()

    @staticmethod
    def _advance_intent_clarification(
        previous: Dict[str, Any],
        uncertain: List[Dict[str, Any]],
        confident: List[Dict[str, Any]] | None = None,
    ) -> tuple[Dict[str, Any], str]:
        """Advance conversation-scoped clarification without touching business state."""
        confident_ids: set[str] = set()
        for item in confident or []:
            if not isinstance(item, dict):
                continue
            confident_ids.update(
                str(value).strip()
                for value in (item.get("clarification_ids", []) or [])
                if str(value).strip()
            )
            clarification_id = str(item.get("clarification_id", "")).strip()
            if clarification_id:
                confident_ids.add(clarification_id)
        previous_round = (
            int(previous.get("round", 0) or 0)
            if previous.get("status") == "waiting_for_clarification"
            else 0
        )
        remaining_previous = [
            dict(item) for item in (previous.get("items", []) or [])
            if isinstance(item, dict)
            and str(item.get("clarification_id", "")) not in confident_ids
        ]
        if not uncertain:
            if remaining_previous:
                return {
                    "status": "waiting_for_clarification",
                    "round": previous_round,
                    "items": remaining_previous,
                }, ""
            return {}, ""
        if previous_round >= 3:
            return {}, "仍无法准确判断您的意图，请使用完整句子重新描述您的需求。"

        previous_items = {
            str(item.get("clarification_id", "")): item
            for item in (previous.get("items", []) or [])
            if isinstance(item, dict) and item.get("clarification_id")
        }
        items: list[dict[str, Any]] = []
        questions: list[str] = []
        for index, item in enumerate(uncertain):
            clarification_id = str(item.get("clarification_id", "")).strip()
            if not clarification_id:
                clarification_id = f"{item.get('intent', 'unknown')}:{index}"
            prior = previous_items.get(clarification_id, {})
            question = str(item.get("clarification_question", "")).strip()
            items.append({
                "clarification_id": clarification_id,
                "original_query": prior.get("original_query") or item.get("query", ""),
                "candidate_intent": item.get("intent", ""),
                "execution_mode": item.get("execution_mode", ""),
                "question": question,
            })
            if question and question not in questions:
                questions.append(question)
        updated_ids = {str(item.get("clarification_id", "")) for item in items}
        items = [
            item for item in remaining_previous
            if str(item.get("clarification_id", "")) not in updated_ids
        ] + items
        return {
            "status": "waiting_for_clarification",
            "round": previous_round + 1,
            "items": items,
        }, "\n".join(questions)

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
    def _format_chat_history(history: List[Dict[str, str]]) -> str:
        """仅保留最近对话，控制最终重写的输入长度。"""
        return "\n".join(
            f"{'用户' if item.get('role') == 'user' else '助手'}: "
            f"{str(item.get('content', ''))[:1200]}"
            for item in history[-4:]
            if item.get("role") in {"user", "assistant"}
        )

    def _synthesize_response(self, state: AdvisorState) -> str:
        """使用大模型重写分析报告；超时或异常时返回原始报告。"""
        draft = state.get("agent_response", "").strip()
        if not draft:
            return draft

        prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                "你是专业、审慎的金融分析助手。直接回答用户当前问题，"
                "不要使用‘基于已验证数据’‘根据提供的数据’等说明信息来源的开场，"
                "也不要展示数据来源、搜索来源、网址或引用。"
                "不得虚构输入材料之外的数据，不得承诺收益，"
                "不得给出保证性买卖结论；数据缺失时明确说明限制。"
                "保留必要的风险提示，使用正式、简洁的中文。仅输出最终回复。",
            ),
            (
                "human",
                "近期对话：\n{history}\n\n当前问题：{message}\n\n"
                "分析材料：\n{draft}\n\n请直接生成最终回复：",
            ),
        ])
        synthesis_model = get_model_for_agent(
            "fundamental",
            timeout=FINAL_SYNTHESIS_TIMEOUT,
            max_retries=0,
        )
        chain = prompt | synthesis_model | StrOutputParser()
        result_queue: queue.Queue[tuple[bool, str]] = queue.Queue(maxsize=1)

        def invoke() -> None:
            try:
                response = chain.invoke({
                    "history": self._format_chat_history(state.get("chat_history", [])),
                    "message": state["user_message"][:2000],
                    "draft": draft[:8000],
                }).strip()
                result_queue.put((True, response))
            except Exception as exc:
                result_queue.put((False, str(exc)))

        worker = threading.Thread(target=invoke, daemon=True, name="final-synthesis")
        worker.start()
        worker.join(timeout=FINAL_SYNTHESIS_TIMEOUT)
        if worker.is_alive():
            print(
                f"[Final Synthesis] timed out after {FINAL_SYNTHESIS_TIMEOUT:.0f}s; "
                "using verified draft",
                flush=True,
            )
            return self._clean_user_facing_response(draft)

        try:
            succeeded, value = result_queue.get_nowait()
        except queue.Empty:
            return self._clean_user_facing_response(draft)
        if not succeeded or not value:
            print(f"[Final Synthesis] failed: {value}; using verified draft", flush=True)
            return self._clean_user_facing_response(draft)
        return self._clean_user_facing_response(value)

    @staticmethod
    def _clean_user_facing_response(response: str) -> str:
        """移除内部数据标签和来源展示，保持回答直接面向用户。"""
        import re

        cleaned = (response or "").strip()
        cleaned = re.sub(
            r"^(?:基于已验证数据|根据已验证数据|基于提供的数据|根据提供的数据)[，,：:\s]*",
            "",
            cleaned,
        )
        cleaned = re.sub(
            r"(?m)^\s*[-*]?\s*\*{0,2}(?:搜索来源|数据来源|信息来源|参考来源)\*{0,2}\s*[：:].*(?:\n|$)",
            "",
            cleaned,
        )
        return cleaned.strip()

    def _build_stock_analysis_summary(
        self, analysis: Dict[str, Any], codes: List[str], screening: bool = False
    ) -> str:
        """根据股票分析结果生成摘要回复（跳过 asset_allocation 时使用）。"""
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

        title = "## 候选股票分析对比" if screening else "## 股票分析报告"
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
            # 技术面分析（如 Agent 返回了 technical_analysis）
            tech = a.get("technical_analysis")
            if isinstance(tech, dict):
                trend = tech.get("trend", "")
                signals = tech.get("signals", []) or []
                risks_tech = tech.get("risks", []) or []
                if trend:
                    parts.append(f"- **技术趋势**：{trend}")
                # 展示各指标的具体数值
                indicators_map = tech.get("indicators", {}) or {}
                for ind_name, ind_data in indicators_map.items():
                    if not isinstance(ind_data, dict):
                        continue
                    line = _format_indicator_line(ind_name, ind_data)
                    if line:
                        parts.append(f"- **{ind_name}**：{line}")
                if signals:
                    parts.append(f"- **技术信号**：{'；'.join(signals[:5])}")
                if risks_tech:
                    parts.append(f"- **技术风险**：{'；'.join(risks_tech[:5])}")
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

    @staticmethod
    def _intent_names(state: AdvisorState) -> set[str]:
        return {
            str(item.get("intent", ""))
            for item in (state.get("detected_intents", []) or [])
            if isinstance(item, dict)
        }

    @staticmethod
    def _intent_query(state: AdvisorState, intent: str) -> str:
        for item in state.get("detected_intents", []) or []:
            if isinstance(item, dict) and item.get("intent") == intent:
                return str(item.get("query", "")).strip() or state["user_message"]
        return state["user_message"]

    @staticmethod
    def _intent_plan(state: AdvisorState, intent: str) -> Dict[str, Any]:
        for item in state.get("detected_intents", []) or []:
            if isinstance(item, dict) and item.get("intent") == intent:
                return item
        return {}

    @staticmethod
    def _route_after_fundamental_plan(state: AdvisorState) -> str:
        """Authorize allocation only when the supervisor plan explicitly requests it."""
        task_plan = state.get("task_plan", [])
        if not isinstance(task_plan, list) or "asset_allocation" not in task_plan:
            return "compliance"
        resolved = state.get("resolved_stocks", []) or []
        codes = [
            str(stock.get("code"))
            for stock in resolved
            if isinstance(stock, dict) and stock.get("code")
        ]
        if not codes:
            profile = state.get("user_profile", {}) or {}
            if isinstance(profile, dict):
                codes = [str(code) for code in profile.get("stock_codes", []) if code]
        return "asset_allocation" if len(dict.fromkeys(codes)) >= 2 else "compliance"

    @staticmethod
    def _compose_intent_draft(state: AdvisorState) -> str:
        """按用户友好的顺序组合独立工作流结果。"""
        results = state.get("intent_results", {}) or {}
        sections: list[str] = []
        titles = {
            "casual_chat": "交流回应",
            "market_query": "行情与分析",
            "stock_recommendation": "候选标的研究",
            "asset_allocation": "资产配置",
        }
        for intent in ("casual_chat", "market_query", "stock_recommendation", "asset_allocation"):
            item = results.get(intent, {}) or {}
            content = str(item.get("content", "")).strip()
            if content:
                sections.append(f"## {titles[intent]}\n\n{content}")
        return "\n\n".join(sections).strip() or state.get("agent_response", "").strip()

    def _build_graph(self) -> CompiledStateGraph:

        # ── 节点 1: 监督者（选择需要执行的子 Agent）──
        def supervisor_handler(state: AdvisorState) -> AdvisorState:
            self._trace_agent(state, "SupervisorAgent")
            self._emit_progress("supervisor", "正在判断需要执行的分析步骤")
            plan_args = (
                state["user_message"],
                state.get("intent_context", ""),
                (state.get("business_state", {}) or {}).get("status") == "waiting_for_input",
                list((state.get("business_state", {}) or {}).get("missing_fields", []) or []),
            )
            pending_clarification = state.get("intent_clarification_state", {}) or {}
            if pending_clarification:
                result = self.supervisor.plan_tasks(*plan_args, pending_clarification)
            else:
                result = self.supervisor.plan_tasks(*plan_args)
            pending = state.get("business_state", {}) or {}
            state["task_plan"] = result["task_plan"]
            state["detected_intents"] = result["intents"]
            state["uncertain_intents"] = list(result.get("uncertain_intents", []) or [])
            state["intent_source"] = result["intent_source"]
            state["finance_related"] = bool(result["finance_related"])
            if state["intent_source"] == "classification_error":
                state["agent_response"] = "意图识别暂时不可用，请稍后重试。"
                state["intent_clarification_response"] = ""
            else:
                clarification_state, clarification_response = self._advance_intent_clarification(
                    pending_clarification,
                    state["uncertain_intents"],
                    state["detected_intents"],
                )
                state["intent_clarification_state"] = clarification_state
                state["intent_clarification_response"] = clarification_response
                if not state["detected_intents"] and clarification_response:
                    state["agent_response"] = clarification_response
            allocation_plan = self._intent_plan(state, "asset_allocation")
            continues_allocation = (
                allocation_plan.get("execution_mode") == "allocation"
            )
            if pending.get("status") == "waiting_for_input" and continues_allocation:
                state["resolved_stocks"] = list(pending.get("resolved_stocks", []) or [])
            elif pending.get("status") == "waiting_for_input":
                state["business_state"] = {}
            print(
                f"[Agent Plan] {state['customer_id']} | {state['thread_id']} | "
                + " -> ".join(state["task_plan"]),
                flush=True,
            )
            return state

        def route_after_supervisor(state: AdvisorState) -> str:
            if state.get("intent_source") == "classification_error":
                return "compliance"
            if state.get("uncertain_intents") and not state.get("detected_intents"):
                return "compliance"
            business = self._intent_names(state) & {
                "market_query", "stock_recommendation", "asset_allocation",
            }
            return "slot_tool_decision" if business else "casual_chat"

        def _slot_candidate_intents(state: AdvisorState) -> Dict[str, str]:
            """返回业务上可能需要槽位工具的意图及其独立子请求。"""
            candidates: dict[str, str] = {}
            for intent in self._intent_names(state):
                plan = self._intent_plan(state, intent)
                if requires_slot_extraction(plan):
                    candidates[intent] = self._intent_query(state, intent)
            return candidates

        def slot_tool_decision_handler(state: AdvisorState) -> AdvisorState:
            """让轻量模型通过原生 tool_calls 决定需要提取槽位的意图。"""
            candidates = _slot_candidate_intents(state)
            if not candidates:
                state["slot_tool_calls"] = []
                state["slot_tool_source"] = "skipped"
                return state

            candidate_items = [
                item for item in state.get("detected_intents", [])
                if isinstance(item, dict) and item.get("intent") in candidates
            ]
            slot_tool = create_extract_finance_slots_tool(
                self.finance_slots_extractor,
                state.get("user_profile", {}) or {},
                self._format_chat_history(state.get("chat_history", [])),
            )
            source = "model"
            error = ""
            try:
                raw_calls = self.supervisor.decide_slot_tool_calls(
                    candidate_items,
                    slot_tool,
                    self._format_chat_history(state.get("chat_history", [])),
                    (state.get("business_state", {}) or {}).get("status") == "waiting_for_input",
                )
            except Exception as exc:
                raw_calls = []
                source = "deterministic_fallback"
                error = str(exc)

            valid: dict[str, dict[str, Any]] = {}
            if not isinstance(raw_calls, list):
                raw_calls = []
                source = "deterministic_fallback"
            for call in raw_calls:
                if not isinstance(call, dict):
                    continue
                if call.get("name") != "extract_finance_slots":
                    continue
                args = call.get("args")
                if not isinstance(args, dict):
                    continue
                intent = str(args.get("intent", ""))
                query = str(args.get("query", "")).strip()
                if intent not in candidates or query != candidates[intent] or intent in valid:
                    continue
                valid[intent] = {
                    "name": "extract_finance_slots",
                    "args": {"intent": intent, "query": query},
                    "id": str(call.get("id", "")),
                }

            # 这些候选已经过确定性业务边界筛选；模型漏调时保障业务可继续。
            missing = [intent for intent in candidates if intent not in valid]
            if missing:
                source = "deterministic_fallback" if not valid else "model+fallback"
                for intent in missing:
                    valid[intent] = {
                        "name": "extract_finance_slots",
                        "args": {"intent": intent, "query": candidates[intent]},
                        "id": "",
                    }

            state["slot_tool_calls"] = list(valid.values())
            state["slot_tool_source"] = source
            state["slot_tool_error"] = error
            return state

        def route_after_slot_tool_decision(state: AdvisorState) -> str:
            return "slot_tool_executor" if state.get("slot_tool_calls") else "business_state_guard"

        def slot_tool_executor_handler(state: AdvisorState) -> AdvisorState:
            """执行经校验的槽位工具调用，并按意图合并结构化结果。"""
            calls = state.get("slot_tool_calls", []) or []
            if not calls:
                return state
            self._trace_agent(state, "SlotExtractionTool")
            self._emit_progress("slot_extraction", "正在提取画像与股票等关键信息")
            user_profile = dict(state.get("user_profile", {}) or {})
            all_stocks = list(state.get("resolved_stocks", []) or [])
            intent_stocks = dict(state.get("intent_stocks", {}) or {})
            explicit_codes = list(state.get("explicit_user_stock_codes", []) or [])
            errors: list[str] = []

            for call in calls:
                args = call.get("args", {}) or {}
                intent = str(args.get("intent", ""))
                try:
                    slot_tool = create_extract_finance_slots_tool(
                        self.finance_slots_extractor,
                        user_profile,
                        self._format_chat_history(state.get("chat_history", [])),
                    )
                    result = slot_tool.invoke(args)
                    if not isinstance(result, dict):
                        raise ValueError("槽位工具返回值必须是字典")

                    extracted_profile = result.get("user_profile", {}) or {}
                    stocks = result.get("resolved_stocks", []) or []
                    result_explicit_codes = result.get("explicit_stock_codes", []) or []
                    if not isinstance(extracted_profile, dict):
                        raise ValueError("user_profile 必须是字典")
                    if not isinstance(stocks, list) or not all(
                        isinstance(stock, dict) for stock in stocks
                    ):
                        raise ValueError("resolved_stocks 必须是字典列表")
                    if not isinstance(result_explicit_codes, list):
                        raise ValueError("explicit_stock_codes 必须是列表")

                    next_profile = dict(user_profile)
                    for key, value in extracted_profile.items():
                        if key != "stock_codes" and value not in (None, "", 0, [], {}):
                            next_profile[key] = value
                    next_all_stocks = list(all_stocks)
                    known = {
                        str(stock.get("code"))
                        for stock in next_all_stocks
                        if isinstance(stock, dict) and stock.get("code")
                    }
                    for stock in stocks:
                        if stock.get("code") and str(stock["code"]) not in known:
                            next_all_stocks.append(stock)
                            known.add(str(stock["code"]))
                    next_explicit_codes = list(explicit_codes)
                    next_explicit_codes.extend(
                        str(code) for code in result_explicit_codes if code
                    )
                except Exception as exc:
                    errors.append(f"{intent}: {exc}")
                    continue

                user_profile = next_profile
                all_stocks = next_all_stocks
                explicit_codes = next_explicit_codes
                intent_stocks[intent] = stocks

            pending = state.get("business_state", {}) or {}
            if not all_stocks and pending.get("status") == "waiting_for_input":
                all_stocks = list(pending.get("resolved_stocks", []) or [])
            codes = list(dict.fromkeys(
                str(stock.get("code")) for stock in all_stocks if stock.get("code")
            ))
            user_profile["stock_codes"] = codes
            state["user_profile"] = user_profile
            state["resolved_stocks"] = all_stocks
            state["intent_stocks"] = intent_stocks
            state["explicit_user_stock_codes"] = list(dict.fromkeys(explicit_codes))
            state["slot_tool_called"] = True
            if errors:
                state["slot_tool_error"] = "; ".join(errors)
            if "slot_extraction" not in state.get("task_plan", []):
                state["task_plan"] = ["slot_extraction", *state.get("task_plan", [])]
            self.shared_memory.publish_fact(
                "user_profile", user_profile, source="slot_extraction_tool",
            )
            return state

        def business_state_guard(state: AdvisorState) -> AdvisorState:
            """在任何外部搜索或数据获取前校验目标 Agent 的业务状态。"""
            if "asset_allocation" not in (state.get("task_plan", []) or []):
                state["business_state"] = {}
                return state

            business_state = self.allocation_agent.build_business_state(
                state.get("user_profile", {}) or {}
            )
            # 选股工作流会在下一节点产生配置候选，因此此处只校验其余画像字段。
            if "stock_recommendation" in self._intent_names(state):
                business_state["missing_fields"] = [
                    field for field in business_state.get("missing_fields", [])
                    if field != "stock_codes"
                ]
                business_state["status"] = (
                    "waiting_for_input" if business_state["missing_fields"] else "ready"
                )
            previous = state.get("business_state", {}) or {}
            if business_state["status"] == "waiting_for_input":
                business_state.update({
                    "original_request": previous.get("original_request") or state["user_message"],
                    "task_plan": previous.get("task_plan") or list(state.get("task_plan", [])),
                    "resolved_stocks": list(state.get("resolved_stocks", []) or []),
                })
                state["agent_response"] = (
                    self.allocation_agent.build_missing_fields_response(business_state)
                )
                intent_results = state.get("intent_results", {}) or {}
                intent_results["asset_allocation"] = {
                    "status": "waiting_for_input", "content": state["agent_response"],
                }
                state["intent_results"] = intent_results
                if self._intent_names(state) & {"market_query", "stock_recommendation"}:
                    state["task_plan"] = [
                        step for step in state.get("task_plan", [])
                        if step != "asset_allocation"
                    ]
                    remaining_modes = {
                        str(item.get("execution_mode", ""))
                        for item in state.get("detected_intents", []) or []
                        if isinstance(item, dict)
                        and item.get("intent") != "asset_allocation"
                    }
                    if not remaining_modes & {
                        "security_analysis", "candidate_search", "security_comparison",
                    }:
                        state["task_plan"] = [
                            step for step in state.get("task_plan", [])
                            if step not in {"data_fetch", "fundamental_analysis"}
                        ]
            state["business_state"] = business_state
            return state

        def route_after_business_guard(state: AdvisorState) -> str:
            if (state.get("business_state", {}) or {}).get("status") == "waiting_for_input":
                if self._intent_names(state) & {"market_query", "stock_recommendation"}:
                    return "stock_resolution"
                return "compliance"
            return "stock_resolution"

        def stock_resolution_handler(state: AdvisorState) -> AdvisorState:
            """校验通过后再执行候选搜索和股票身份整理。"""
            message = state["user_message"]
            resolved = list(state.get("resolved_stocks", []) or [])
            user_profile = state.get("user_profile", {}) or {}
            intent_names = self._intent_names(state)
            intent_results = state.get("intent_results", {}) or {}
            intent_stocks = state.get("intent_stocks", {}) or {}

            market_mode = self._intent_plan(state, "market_query").get("execution_mode")
            recommendation_mode = self._intent_plan(
                state, "stock_recommendation",
            ).get("execution_mode")

            for intent in ("market_query", "stock_recommendation"):
                if self._intent_plan(state, intent).get("execution_mode") == "unsupported":
                    intent_results[intent] = {
                        "status": "error",
                        "content": "监督者未提供可执行策略，请补充具体分析目标后重试。",
                    }

            if "market_query" in intent_names and market_mode == "market_overview":
                try:
                    self._emit_progress("stock_search", "正在搜索板块与行业市场资料")
                    market_response = self.stock_search.search_market_overview(
                        self._intent_query(state, "market_query")
                    )
                    intent_results["market_query"] = {
                        "status": "success", "content": market_response,
                    }
                except WebSearchError as exc:
                    intent_results["market_query"] = {
                        "status": "error", "content": "市场资料搜索失败：" + str(exc),
                    }
                state["intent_results"] = intent_results

            if (
                "data_fetch" in (state.get("task_plan", []) or [])
                and "stock_recommendation" in intent_names
                and recommendation_mode == "candidate_search"
                and not intent_stocks.get("stock_recommendation")
            ):
                try:
                    self._emit_progress("stock_search", "正在搜索相关行业的A股候选")
                    candidates = self.stock_search.search(
                        self._intent_query(state, "stock_recommendation")
                    )
                    state["candidate_stocks"] = candidates
                    intent_stocks["stock_recommendation"] = list(candidates)
                    by_code = {
                        str(stock.get("code")): stock for stock in resolved
                        if isinstance(stock, dict) and stock.get("code")
                    }
                    for stock in candidates:
                        if stock.get("code") not in by_code:
                            resolved.append(stock)
                    self._emit_progress("stock_validation", "候选代码已确认，准备获取权威证券信息")
                except WebSearchError as exc:
                    state["stock_search_error"] = str(exc)
                    intent_results["stock_recommendation"] = {
                        "status": "error",
                        "content": "候选股票搜索失败：" + str(exc),
                    }

            if (
                not resolved
                and not state.get("stock_search_error")
                and "data_fetch" in (state.get("task_plan", []) or [])
            ):
                state["stock_resolution_error"] = (
                    "无法从当前问题和对话历史中确定需要分析的股票，"
                    "请提供股票名称或六位股票代码。"
                )
                state["agent_response"] = state["stock_resolution_error"]
                target = (
                    "stock_recommendation"
                    if "stock_recommendation" in intent_names else "market_query"
                )
                intent_results[target] = {
                    "status": "error", "content": state["stock_resolution_error"],
                }

            if not resolved and isinstance(user_profile, dict):
                user_profile["stock_codes"] = []
            elif resolved and isinstance(user_profile, dict):
                user_profile["stock_codes"] = list(dict.fromkeys(
                    stock["code"] for stock in resolved if stock.get("code")
                ))
            state["user_profile"] = user_profile
            state["resolved_stocks"] = resolved
            state["intent_results"] = intent_results
            state["intent_stocks"] = intent_stocks
            self.shared_memory.publish_fact("user_profile", user_profile, source="slot_extraction")

            # 把每只股票的基本识别信息写入共享内存（供下游展示）
            for s in resolved:
                if self.shared_memory and s.get("name"):
                    self.shared_memory.publish_fact(
                        f"stock_basic_info_{s['code']}",
                        {"code": s["code"], "name": s["name"], "industry": s.get("industry", "")},
                        source="slot_extraction",
                    )
                if s.get("source") == "eastmoney_sector":
                    self.shared_memory.publish_fact(
                        f"stock_search_candidate_{s['code']}", s, source="eastmoney_sector"
                    )

            return state

        # ── 节点 4: 金融数据获取（@task fan-out 按股票并行）──

        def _resolve_stock_codes(state: AdvisorState) -> List[str]:
            """解析股票代码：优先 resolved_stocks，其次 user_profile，最后正则。"""
            def _unique_codes(values: List[Any]) -> List[str]:
                return list(dict.fromkeys(str(value) for value in values if value))[:5]

            # 1. 优先从 LLM 识别结果读取
            resolved = state.get("resolved_stocks", []) or []
            if resolved:
                return _unique_codes([s.get("code") for s in resolved])
            # 2. 从 user_profile 读取
            user_profile = state.get("user_profile", {}) or {}
            if isinstance(user_profile, dict):
                codes = list(user_profile.get("stock_codes", []))
                if codes:
                    return _unique_codes(codes)
            # 3. 正则兜底
            codes = re.findall(
                r"(?<!\d)(60\d{4}|00\d{4}|30\d{4}|68\d{4}|8\d{5}|4\d{5})(?!\d)",
                state.get("user_message", ""),
            )
            return _unique_codes(codes)

        def route_after_slots(state: AdvisorState) -> str:
            if "data_fetch" not in (state.get("task_plan", []) or []):
                return "compliance"
            return "data_fetch_batch"

        def route_after_data_fetch(state: AdvisorState):
            if state.get("stock_search_error") or state.get("stock_resolution_error"):
                return "compliance"
            plan = state.get("task_plan", []) or []
            if "fundamental_analysis" in plan:
                return "fundamental_batch"
            if "asset_allocation" in plan:
                return "asset_allocation"
            return "compliance"

        @task
        def fetch_stock_task(payload: Dict[str, Any]) -> Dict[str, Any]:
            """获取一只股票；返回值由 LangGraph checkpoint 持久化。"""
            code = str(payload["code"])
            try:
                entry = self.data_fetch_agent.handle_single_stock(code)
                entry.setdefault("status", "success")
            except Exception as exc:
                entry = {"code": code, "status": "error", "error": str(exc)}
            entry["code"] = code
            entry["_run_id"] = str(payload.get("run_id", ""))
            return entry

        def _publish_stock_entry(entry: Dict[str, Any]) -> None:
            """从 task 返回值重建共享内存，确保 checkpoint 恢复不依赖副作用。"""
            code = str(entry.get("code", ""))
            if not code:
                return
            fact_names = {
                "basic_info": "stock_basic_info",
                "quote": "stock_quote",
                "indicators": "financial_indicator",
                "history": "stock_history",
            }
            for field, prefix in fact_names.items():
                value = entry.get(field)
                if isinstance(value, dict):
                    self.shared_memory.publish_fact(
                        f"{prefix}_{code}", value, source=self.data_fetch_agent.agent_name,
                    )

        def data_fetch_batch_handler(state: AdvisorState) -> AdvisorState:
            """并发获取全部股票，并在 task 完成后统一聚合和发布结果。"""
            codes = _resolve_stock_codes(state)
            payloads = [
                {"code": code, "run_id": state.get("run_id", "")}
                for code in codes
            ]
            futures = []
            for payload in payloads:
                code = payload["code"]
                self._trace_agent(state, "DataFetchAgent", code)
                self._emit_progress(
                    "data_fetch", f"正在获取 {code} 的行情与财务数据",
                    str(state.get("thread_id", "")),
                )
                futures.append(fetch_stock_task(payload))
            entries = [future.result() for future in futures]
            state["stock_data_entries"] = entries

            stock_data: Dict[str, Any] = {}
            for entry in entries:
                if entry.get("_run_id") != state.get("run_id", ""):
                    continue
                _publish_stock_entry(entry)
                code = str(entry.get("code", ""))
                if not code:
                    continue
                stock_data[code] = {
                    "quote": entry.get("quote", {}),
                    "indicators": entry.get("indicators", {}),
                    "basic_info": entry.get("basic_info", {}),
                    "history": entry.get("history", {}),
                }
            state["stock_data"] = stock_data
            if state.get("stock_search_error"):
                state["agent_response"] = (
                    "无法确定需要分析的股票候选：" + state["stock_search_error"]
                    + "。请直接提供股票名称/代码。"
                )
                return state
            if "fundamental_analysis" not in (state.get("task_plan", []) or []):
                if not stock_data:
                    # 保留股票解析/搜索阶段已经生成的明确错误，不用空模板覆盖。
                    if not state.get("agent_response"):
                        state["agent_response"] = (
                            "未找到可查询的股票，请提供股票名称或六位股票代码。"
                        )
                    return state
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
                if "market_query" in self._intent_names(state):
                    intent_results = state.get("intent_results", {}) or {}
                    intent_results["market_query"] = {
                        "status": "success", "content": state["agent_response"],
                    }
                    state["intent_results"] = intent_results
            return state

        # ── 节点 5: 股票综合分析（@task fan-out 按股票并行）──

        @task
        def analyze_stock_task(payload: Dict[str, Any]) -> Dict[str, Any]:
            """分析一只股票；输入中的数据先用于恢复共享内存。"""
            code = str(payload["code"])
            stock_item = payload.get("stock_data", {})
            if isinstance(stock_item, dict):
                _publish_stock_entry({"code": code, **stock_item})
            try:
                entry = self.stock_agent.handle_single_stock(
                    code,
                    user_message=payload.get("user_message", ""),
                    memory_context=payload.get("memory_context", ""),
                )
                entry.setdefault("status", "success")
            except Exception as exc:
                entry = {
                    "code": code,
                    "status": "error",
                    "error": str(exc),
                    "rating": "未知",
                    "summary": "股票分析执行异常",
                    "overall_score": 50,
                }
            entry["code"] = code
            entry["_run_id"] = str(payload.get("run_id", ""))
            return entry

        def stock_analysis_batch_handler(state: AdvisorState) -> AdvisorState:
            """并发分析全部股票，并统一聚合分析结果。

            当 task_plan 不包含 asset_allocation 时，同时生成分析摘要回复。
            """
            codes = _resolve_stock_codes(state)
            stock_data = state.get("stock_data", {}) or {}
            payloads = [
                {
                    "code": code,
                    "run_id": state.get("run_id", ""),
                    "stock_data": stock_data.get(code, {}),
                    "user_message": state.get("user_message", ""),
                    "memory_context": state.get("memory_context", ""),
                }
                for code in codes
            ]
            futures = []
            for payload in payloads:
                code = payload["code"]
                self._trace_agent(state, "StockAnalysisAgent", code)
                self._emit_progress(
                    "stock_analysis", f"正在分析 {code}",
                    str(state.get("thread_id", "")),
                )
                futures.append(analyze_stock_task(payload))
            entries = [future.result() for future in futures]
            state["stock_analysis_entries"] = entries

            analysis: Dict[str, Any] = {}
            technical: Dict[str, Any] = {}
            for entry in entries:
                if entry.get("_run_id") != state.get("run_id", ""):
                    continue
                code = str(entry.get("code", ""))
                if not code:
                    continue
                result = {key: value for key, value in entry.items() if key != "_run_id"}
                analysis[code] = result
                # Extract technical analysis from result if present
                tech_result = entry.get("technical_analysis")
                if isinstance(tech_result, dict):
                    technical[code] = tech_result
                self.shared_memory.publish_fact(
                    f"fundamental_analysis_{code}",
                    result,
                    source=self.stock_agent.agent_name,
                )
            state["stock_analysis"] = analysis
            state["technical_analysis"] = technical

            # 条件路由：task_plan 不含 asset_allocation 或股票数 < 2 时，生成分析摘要回复
            task_plan = state.get("task_plan", []) or []
            if "asset_allocation" not in task_plan or len(codes) < 2:
                state["agent_response"] = self._build_stock_analysis_summary(
                    analysis, codes, screening=bool(state.get("candidate_stocks"))
                )

            intent_results = state.get("intent_results", {}) or {}
            intent_names = self._intent_names(state)
            intent_stocks = state.get("intent_stocks", {}) or {}
            def codes_for(intent: str) -> List[str]:
                scoped = [
                    str(stock.get("code"))
                    for stock in intent_stocks.get(intent, [])
                    if isinstance(stock, dict) and stock.get("code")
                ]
                return list(dict.fromkeys(scoped)) or codes

            if "stock_recommendation" in intent_names:
                recommendation_codes = codes_for("stock_recommendation")
                recommendation_analysis = {
                    code: analysis[code] for code in recommendation_codes if code in analysis
                }
                summary = self._build_stock_analysis_summary(
                    recommendation_analysis, recommendation_codes, screening=True,
                )
                intent_results["stock_recommendation"] = {
                    "status": "success" if recommendation_analysis else "error",
                    "content": summary,
                }
            if (
                "market_query" in intent_names
                and self._intent_plan(state, "market_query").get("execution_mode")
                == "security_analysis"
            ):
                market_codes = codes_for("market_query")
                market_analysis = {
                    code: analysis[code] for code in market_codes if code in analysis
                }
                summary = self._build_stock_analysis_summary(
                    market_analysis, market_codes, screening=False,
                )
                intent_results["market_query"] = {
                    "status": "success" if market_analysis else "error", "content": summary,
                }
            state["intent_results"] = intent_results

            return state

        def route_after_fundamental(state: AdvisorState) -> str:
            return self._route_after_fundamental_plan(state)

        # ── 节点 5: 资产配置 ──
        def asset_allocation_handler(state: AdvisorState) -> AdvisorState:
            self._trace_agent(state, "AssetAllocationAgent")
            self._emit_progress("asset_allocation", "正在计算资产配置方案")
            # 健壮性保障：确保 shared_memory 的 user_profile.stock_codes 与 state 一致
            user_profile = state.get("user_profile", {}) or {}
            resolved_stocks = state.get("resolved_stocks", []) or []
            intent_stocks = state.get("intent_stocks", {}) or {}
            allocation_stocks = intent_stocks.get("asset_allocation", []) or []
            recommendation_stocks = intent_stocks.get("stock_recommendation", []) or []
            recommendation_mode = self._intent_plan(
                state, "stock_recommendation",
            ).get("execution_mode")
            if allocation_stocks:
                resolved_stocks = list(allocation_stocks)
            elif recommendation_stocks and recommendation_mode == "candidate_search":
                resolved_stocks = list(recommendation_stocks)
            if isinstance(user_profile, dict) and resolved_stocks:
                codes = [s.get("code") for s in resolved_stocks if isinstance(s, dict) and s.get("code")]
                if codes and list(user_profile.get("stock_codes", [])) != codes:
                    user_profile["stock_codes"] = codes
                    state["user_profile"] = user_profile
                    self.shared_memory.publish_fact(
                        "user_profile", user_profile, source="asset_allocation_sync"
                    )

            response = self.allocation_agent.handle(
                message=state["user_message"],
                customer_id=state["customer_id"],
                chat_history=state.get("chat_history", []),
                thread_id=state.get("thread_id"),
                memory_context=state.get("memory_context", ""),
            )
            state["agent_response"] = response
            state["allocation_result"] = self.shared_memory.query("allocation_result", {}) or {}
            intent_results = state.get("intent_results", {}) or {}
            intent_results["asset_allocation"] = {
                "status": "success" if state["allocation_result"] else "error",
                "content": response,
            }
            state["intent_results"] = intent_results
            return state

        def casual_chat_handler(state: AdvisorState) -> AdvisorState:
            """处理拆分后的理财闲聊，不触发任何金融数据工具。"""
            if "casual_chat" not in self._intent_names(state):
                return state
            intent_results = state.get("intent_results", {}) or {}
            if intent_results.get("casual_chat", {}).get("content"):
                return state
            self._trace_agent(state, "CasualChatAgent")
            self._emit_progress("casual_chat", "正在回应理财交流内容")
            try:
                response = self.supervisor.chat(
                    self._intent_query(state, "casual_chat"),
                    self._format_chat_history(state.get("chat_history", [])),
                    state.get("finance_related", True),
                )
                status = "success"
            except Exception as exc:
                response = "暂时无法回应这部分交流内容：" + str(exc)
                status = "error"
            intent_results["casual_chat"] = {"status": status, "content": response}
            state["intent_results"] = intent_results
            state["agent_response"] = response
            return state

        # ── 节点 6: 合规风控审查 ──
        def compliance_handler(state: AdvisorState) -> AdvisorState:
            self._trace_agent(state, "ComplianceAgent")
            self._emit_progress("compliance", "正在检查回复中的合规表述")
            if "casual_chat" in self._intent_names(state):
                state = casual_chat_handler(state)

            # 某些分支（如缺少配置字段）直接在 agent_response 中产生提示，
            # 在最终综合前把它归入对应意图，避免覆盖其他成功结果。
            intent_results = state.get("intent_results", {}) or {}
            if (
                "asset_allocation" in self._intent_names(state)
                and "asset_allocation" not in intent_results
                and state.get("agent_response")
            ):
                intent_results["asset_allocation"] = {
                    "status": "waiting_for_input",
                    "content": state["agent_response"],
                }
            state["intent_results"] = intent_results
            state["agent_response"] = self._compose_intent_draft(state)

            has_verified_analysis = bool(
                state.get("stock_analysis")
                or state.get("allocation_result")
                or state.get("stock_data")
            )
            if (
                (has_verified_analysis or len(intent_results) > 1)
                and state.get("agent_response")
            ):
                state["agent_response"] = self._synthesize_response(state)
            clarification_response = str(
                state.get("intent_clarification_response", "") or ""
            ).strip()
            if (
                clarification_response
                and clarification_response not in state.get("agent_response", "")
            ):
                separator = "\n\n" if state.get("agent_response") else ""
                state["agent_response"] = (
                    state.get("agent_response", "") + separator + clarification_response
                )
            result = self.compliance_agent.review(
                agent_response=state["agent_response"],
            )
            state["compliance_result"] = result

            # 合规不通过 → 附加合规提示到回复（保留用户体验，移除升级人工标记）
            if not result.get("pass", True):
                state["agent_response"] = (
                    state["agent_response"]
                    + "\n\n---\n⚠️ 合规提示："
                    + result.get("reason", "回复中存在敏感表述，请修改后参考。")
                )

            return state

        def final_snapshot(state: AdvisorState) -> AdvisorState:
            state["shared_memory_snapshot"] = self.shared_memory.snapshot()
            return state

        # ── 构建图 ─────────────────────────────────────────
        # START → supervisor → slot_extraction（画像与股票识别）
        #       → data_fetch_batch（@task × N 并行）
        #       → stock_analysis_batch（@task × N 并行）
        #       → route_after_fundamental ─┬─ asset_allocation → compliance
        #                                └──────────────────→ compliance
        #       → final_snapshot → END

        graph = StateGraph(AdvisorState)

        graph.add_node("supervisor", supervisor_handler)
        graph.add_node("slot_tool_decision", slot_tool_decision_handler)
        graph.add_node("slot_tool_executor", slot_tool_executor_handler)
        graph.add_node("business_state_guard", business_state_guard)
        graph.add_node("stock_resolution", stock_resolution_handler)

        graph.add_node("data_fetch_batch", data_fetch_batch_handler)
        graph.add_node("fundamental_batch", stock_analysis_batch_handler)

        graph.add_node("asset_allocation", asset_allocation_handler)
        graph.add_node("casual_chat", casual_chat_handler)
        graph.add_node("compliance", compliance_handler)
        graph.add_node("final_snapshot", final_snapshot)

        # 边：顺序段
        graph.add_edge(START, "supervisor")
        graph.add_conditional_edges(
            "supervisor",
            route_after_supervisor,
            ["slot_tool_decision", "casual_chat", "compliance"],
        )
        graph.add_edge("casual_chat", "compliance")
        graph.add_conditional_edges(
            "slot_tool_decision",
            route_after_slot_tool_decision,
            ["slot_tool_executor", "business_state_guard"],
        )
        graph.add_edge("slot_tool_executor", "business_state_guard")
        graph.add_conditional_edges(
            "business_state_guard",
            route_after_business_guard,
            ["stock_resolution", "compliance"],
        )
        graph.add_conditional_edges(
            "stock_resolution",
            route_after_slots,
            ["data_fetch_batch", "compliance"],
        )

        # 数据批处理完成后，根据 task_plan 决定是否继续基本面、配置或合规。
        graph.add_conditional_edges(
            "data_fetch_batch",
            route_after_data_fetch,
            ["fundamental_batch", "asset_allocation", "compliance"],
        )

        # 顺序下游段
        # 条件路由：根据 task_plan 决定是否执行 asset_allocation
        graph.add_conditional_edges(
            "fundamental_batch",
            route_after_fundamental,
            ["asset_allocation", "compliance"],
        )
        graph.add_edge("asset_allocation", "compliance")
        graph.add_edge("compliance", "final_snapshot")
        graph.add_edge("final_snapshot", END)

        return graph.compile(checkpointer=self.checkpointer)

    # ── 公共 API ─────────────────────────────────────────────

    def handle_message(
        self,
        message: str,
        chat_history: List[Dict[str, str]] | None = None,
        customer_id: str = "CUST001",
        progress_callback: Callable[[str, str], None] | None = None,
        conversation_id: str = "",
    ) -> Dict[str, Any]:
        """隔离并执行一轮完整工作流。"""
        with self._workflow_lock:
            self.shared_memory.reset()
            return self._handle_message_locked(
                message, chat_history, customer_id, progress_callback, conversation_id,
            )

    def _handle_message_locked(
        self,
        message: str,
        chat_history: List[Dict[str, str]] | None = None,
        customer_id: str = "CUST001",
        progress_callback: Callable[[str, str], None] | None = None,
        conversation_id: str = "",
    ) -> Dict[str, Any]:
        """处理用户消息，返回投顾回复。"""
        # Guard the orchestration boundary before memory, LLM, search, or market-data
        # processing. The individual ReAct agents also use the same before_agent
        # middleware as defence in depth.
        if find_sensitive_word(message) is not None:
            self._emit_progress("content_filter", "输入内容未通过安全检查")
            return {
                "response": BLOCKED_RESPONSE,
                "task_plan": [],
                "user_profile": {},
                "stock_data": {},
                "fundamental_analysis": {},
                "technical_analysis": {},
                "allocation_result": {},
                "compliance_result": {},
                "shared_memory_snapshot": {},
                "explicit_user_stock_codes": [],
                "conversation_id": conversation_id or uuid.uuid4().hex,
                "blocked": True,
            }
        self._progress_context.callback = progress_callback
        self._emit_progress("preparing", "正在准备分析上下文")

        # conversation_id 即 checkpoint thread_id；未提供时新建
        if not conversation_id:
            conversation_id = uuid.uuid4().hex
        thread_id = conversation_id
        config = {"configurable": {"thread_id": thread_id}}

        previous_business_state: Dict[str, Any] = {}
        previous_clarification_state: Dict[str, Any] = {}
        try:
            previous_values = self.graph.get_state(config).values or {}
            candidate_state = previous_values.get("business_state", {}) or {}
            if candidate_state.get("status") == "waiting_for_input":
                previous_business_state = dict(candidate_state)
            candidate_clarification = (
                previous_values.get("intent_clarification_state", {}) or {}
            )
            if candidate_clarification.get("status") == "waiting_for_clarification":
                previous_clarification_state = dict(candidate_clarification)
        except Exception:
            previous_business_state = {}
            previous_clarification_state = {}

        if progress_callback:
            with self._progress_lock:
                self._progress_callbacks[thread_id] = progress_callback
        fallback_history = chat_history or []
        if not fallback_history and conversation_id:
            # Redis may be unavailable. Recover the recent window from the latest
            # graph checkpoint so contextual follow-ups still receive history.
            fallback_history = self.get_checkpoint_conversation_messages(
                conversation_id, self.memory.window_size,
            )
        memory_data = self.memory.load_context(customer_id, conversation_id, fallback_history)
        effective_history = (
            memory_data.get("sliding_window")
            or fallback_history[-self.memory.window_size:]
        )

        initial_state: AdvisorState = {
            "user_message": message,
            "chat_history": effective_history,
            "customer_id": customer_id,
            "task_plan": [],
            "business_state": previous_business_state,
            "user_profile": memory_data.get("profile", {}) or {},
            "resolved_stocks": [],
            "candidate_stocks": [],
            "stock_search_error": "",
            "stock_resolution_error": "",
            "stock_data": {},
            "stock_analysis": {},
            "technical_analysis": {},
            "allocation_result": {},
            "agent_response": "",
            "compliance_result": {},
            "memory_context": memory_data.get("context_text", ""),
            "intent_context": self.memory.build_intent_context(effective_history),
            "shared_memory_snapshot": {},
            "thread_id": thread_id,
            "run_id": uuid.uuid4().hex,
            "explicit_user_stock_codes": [],
            "stock_data_entries": [],
            "stock_analysis_entries": [],
            "detected_intents": [],
            "intent_results": {},
            "intent_source": "",
            "finance_related": True,
            "intent_stocks": {},
            "slot_tool_calls": [],
            "slot_tool_called": False,
            "slot_tool_source": "skipped",
            "slot_tool_error": "",
            "uncertain_intents": [],
            "intent_clarification_state": previous_clarification_state,
            "intent_clarification_response": "",
        }

        with self._trace_lock:
            self._trace_sequences[thread_id] = 0
        try:
            result = self.graph.invoke(initial_state, config=config)
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
            "stock_analysis": result.get("stock_analysis", {}),
            "allocation_result": result.get("allocation_result", {}),
            "compliance_result": result.get("compliance_result", {}),
            "shared_memory_snapshot": result.get("shared_memory_snapshot", {}),
            "explicit_user_stock_codes": result.get("explicit_user_stock_codes", []),
            "conversation_id": conversation_id,
        }

        # 更新对话记录（finance_agent.db）
        self._update_conversation_meta(conversation_id, message, customer_id)

        # 持久化消息到 finance_agent.db
        try:
            db = get_database()
            db.append_conversation_message(conversation_id, "user", message)
            db.append_conversation_message(
                conversation_id, "assistant", output["response"],
                {"task_plan": output["task_plan"]},
            )
        except Exception:
            pass

        # 更新记忆（按对话隔离）
        self.memory.append_window_message(conversation_id, "user", message)
        self.memory.append_window_message(
            conversation_id, "assistant", output["response"],
            {"task_plan": output["task_plan"]},
        )
        if not (result.get("uncertain_intents", []) or []):
            self.memory.update_profile_from_result(customer_id, message, output)
        self.memory.update_recent_summary(
            conversation_id,
            [
                {"role": "user", "content": message},
                {"role": "assistant", "content": output["response"], "metadata": output},
            ],
        )

        return output

    def _update_conversation_meta(
        self, conversation_id: str, message: str, customer_id: str,
    ) -> None:
        """在 finance_agent.db 中创建或更新对话记录。"""
        try:
            db = get_database()
            existing = db.get_conversation(conversation_id, customer_id)
            if existing:
                db.rename_conversation_from_message(conversation_id, message)
            else:
                default_title = " ".join(message.strip().split())[:28] or "新对话"
                db.create_conversation(customer_id, default_title,
                                       conversation_id=conversation_id)
        except Exception:
            pass

    def list_checkpoint_conversations(self, customer_id: str) -> list[dict[str, Any]]:
        """从 finance_agent.db 查询指定用户的所有对话列表。"""
        try:
            return get_database().list_conversations(customer_id)
        except Exception:
            return []

    def get_checkpoint_conversation_messages(
        self, conversation_id: str, limit: int = 100,
    ) -> list[dict[str, Any]]:
        """从 finance_agent.db 的 conversation_messages 表读取消息。"""
        try:
            return get_database().get_conversation_messages(conversation_id, limit)
        except Exception:
            return []

    def delete_checkpoint_conversation(self, conversation_id: str, customer_id: str) -> bool:
        """删除指定对话的全部数据（finance_agent.db + checkpoint + Redis）。"""
        try:
            db = get_database()
            db.delete_conversation(conversation_id, customer_id)
        except Exception:
            pass
        # 同时清除 checkpoint 中的图状态
        try:
            conn = self.checkpointer.conn
            conn.execute("DELETE FROM writes WHERE thread_id = ?", (conversation_id,))
            conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", (conversation_id,))
            conn.commit()
            # 同时清除 Redis
            self.memory.store.clear_conversation(conversation_id)
            return True
        except Exception:
            return False

    def clear_profile(self, customer_id: str | None = None) -> int:
        """清除用户画像。返回清除数量。"""
        try:
            db = get_database()
            if customer_id:
                count = db.delete_profiles(customer_id)
            else:
                count = db.delete_profiles()
            return count
        except Exception:
            return 0

    async def handle_message_stream(
        self,
        message: str,
        chat_history: List[Dict[str, str]] | None = None,
        customer_id: str = "CUST001",
        conversation_id: str = "",
    ):
        """流式处理消息，逐事件返回。"""
        # 发送阶段事件
        if find_sensitive_word(message) is not None:
            yield {"type": "stage", "stage": "content_filter", "message": "正在检查输入内容..."}
        else:
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
        with self._workflow_lock:
            self.shared_memory.reset()
            if customer_id:
                self._session_counter[customer_id] = self._session_counter.get(customer_id, 0) + 1

    def get_shared_memory_snapshot(self) -> Dict[str, Any]:
        with self._workflow_lock:
            return self.shared_memory.snapshot()

    def get_user_profile(self, customer_id: str) -> Dict[str, Any]:
        """获取用户画像（从 checkpoint 读取）。"""
        from dataclasses import asdict
        profile = self.memory.get_profile(customer_id)
        return asdict(profile)
