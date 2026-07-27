"""监督者 Agent。

职责：根据用户当前问题选择需要执行的子 Agent，并给出执行顺序。

不处理具体业务，仅做编排决策。
"""

from __future__ import annotations

import re
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import BaseTool

from finance_agent.agents.base import BaseFinanceAgent
from finance_agent.config import (
    INTENT_CLASSIFIER_MODE,
    INTENT_DEVICE,
    INTENT_MAX_LENGTH,
    INTENT_MODEL_CACHE_DIR,
    INTENT_SCORE_THRESHOLD,
    INTENT_ZERO_SHOT_MODEL,
    get_intent_model,
    get_supervisor_chat_model,
    safe_parse_json,
)
from finance_agent.intent_classifier import ZeroShotIntentClassifier


_SUPERVISOR_PROMPT = """你是金融投顾系统的多意图分类器。你只负责分类和拆分请求，不回答问题，不生成工作流节点。

必须识别当前消息中所有独立目标。同一意图只返回一次，并把同类目标合并为一个 query。
query 只能包含该意图负责的内容。上下文只用于解析指代，不得根据历史话题添加本轮未表达的意图。

## 业务边界
1. market_query（行情咨询）
- 包含：具体证券的价格、涨跌、成交、估值、财务、业绩、公告、基本面；指数、行业、板块、概念的行情、排行、资金和历史表现。
- 不包含：要求筛选值得投资的标的；要求资金、仓位或权重方案；一般知识、经验、心态或情绪交流。

2. stock_recommendation（选股推荐）
- 包含：推荐、筛选、寻找或比较候选标的、行业龙头、股票池；判断哪只更值得关注或投资。
- 不包含：仅查询客观数据；已经确定标的后要求分配预算；一般投资方法交流。

3. asset_allocation（资产配置）
- 包含：预算、仓位、权重、期限、资金分配；构建、调整、再平衡或优化组合。
- “推荐后怎么配”“筛选股票并分配10万元”同时包含 stock_recommendation 和 asset_allocation。
- 一般性的资产配置知识解释属于 casual_chat。

4. casual_chat（理财闲聊）
- 包含：投资情绪、亏损或踏空后的感受；经验、习惯、纪律、心态、复盘；不要求具体市场数据的一般金融知识；问候和能力咨询。
- 不包含：具体标的、市场、日期或指标的数据查询；筛选标的；个人资金配置方案。
- 完全无关金融的话题也返回 casual_chat，但 finance_related=false。

## 强制规则
- 不得使用优先级丢弃意图；一条消息可以同时返回多个意图。
- 不得仅因出现“股票、投资、基金”等词就添加业务意图。
- 情绪或经验表达与业务请求并存时，必须同时返回 casual_chat 和对应业务意图。
- 若存在等待补充的资产配置任务，预算、风险偏好、期限、标的等短回复必须包含 asset_allocation。
- “什么是市盈率”是 casual_chat；“贵州茅台当前市盈率是多少”是 market_query。
- “分析茅台基本面并告诉我是否值得买”同时是 market_query 和 stock_recommendation。

## 输出格式
只输出合法JSON：
{{"intents":[{{"intent":"market_query|stock_recommendation|asset_allocation|casual_chat","query":"该工作流需要处理的独立子请求","confidence":0.0,"reason":"简短原因","execution_mode":"security_analysis|market_overview|candidate_search|security_comparison|allocation|conversation","requires_slot_extraction":false}}],"finance_related":true}}

execution_mode 必须与 intent 匹配：market_query 使用 security_analysis 或 market_overview；stock_recommendation 使用 candidate_search 或 security_comparison；asset_allocation 使用 allocation；casual_chat 使用 conversation。requires_slot_extraction 仅在 security_analysis、security_comparison、allocation 时为 true。
"""

_INTENTS = ("market_query", "stock_recommendation", "asset_allocation", "casual_chat")
_EXECUTION_MODES = {
    "market_query": {"security_analysis": True, "market_overview": False},
    "stock_recommendation": {"candidate_search": False, "security_comparison": True},
    "asset_allocation": {"allocation": True},
    "casual_chat": {"conversation": False},
}
_NLI_MODE_DEFAULTS = {
    "market_query": "unsupported",
    "stock_recommendation": "candidate_search",
    "asset_allocation": "allocation",
    "casual_chat": "conversation",
}
_CONFIDENCE_THRESHOLD = 0.65
_SHADOW_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="intent-shadow")
_LOGGER = logging.getLogger(__name__)


def normalize_intent_item(
    item: Dict[str, Any], fallback_query: str,
) -> Dict[str, Any] | None:
    """Validate one supervisor intent and attach its executable routing plan."""
    intent = str(item.get("intent", "")).strip()
    if intent not in _INTENTS:
        return None
    try:
        confidence = float(item.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0.0
    mode = str(item.get("execution_mode", "")).strip()
    if mode not in _EXECUTION_MODES[intent]:
        mode = (
            "unsupported"
            if intent in {"market_query", "stock_recommendation"}
            else next(iter(_EXECUTION_MODES[intent]))
        )
    return {
        "intent": intent,
        "query": str(item.get("query", "")).strip() or fallback_query.strip(),
        "confidence": min(max(confidence, 0.0), 1.0),
        "reason": str(item.get("reason", "")).strip(),
        "execution_mode": mode,
        "requires_slot_extraction": bool(
            _EXECUTION_MODES[intent].get(mode, False)
        ),
    }


def needs_stock_screening(message: str) -> bool:
    """仅在当前消息明确要求行业、主题或候选筛选时调用外部搜索。"""
    normalized = (message or "").strip().lower()
    screening_markers = (
        "推荐", "选股", "筛选", "候选", "股票池", "概念股",
        "行业股票", "板块股票", "行业龙头", "板块龙头", "找几只", "来几只",
    )
    return any(marker in normalized for marker in screening_markers)


def needs_market_overview_search(message: str) -> bool:
    """识别不指向个股、需要网页资料回答的板块/行业市场问题。"""
    normalized = (message or "").strip().lower()
    market_scope = ("板块", "行业", "概念")
    research_intent = (
        "涨幅", "跌幅", "领涨", "领跌", "排名", "排行", "最高", "最低",
        "表现", "走势", "资金流入", "资金流出", "热点",
    )
    return (
        any(word in normalized for word in market_scope)
        and any(word in normalized for word in research_intent)
    )


def _has_explicit_stock_reference(query: str) -> bool:
    text = (query or "").strip()
    if re.search(
        r"(?<!\d)(?:60\d{4}|00\d{4}|30\d{4}|68\d{4}|8\d{5}|4\d{5})(?!\d)",
        text,
    ):
        return True
    if any(word in text for word in ("个股", "这只股票", "该股", "这只股")):
        return True
    common_names = (
        "贵州茅台", "茅台", "五粮液", "宁德时代", "招商银行", "招行",
        "浦发银行", "工商银行", "建设银行", "农业银行", "中国银行",
        "中国平安", "比亚迪", "格力电器", "美的集团", "中芯国际",
    )
    return any(name in text for name in common_names)


def _has_non_stock_market_scope(query: str) -> bool:
    text = (query or "").strip()
    markers = (
        "板块", "行业", "概念", "指数", "大盘", "市场整体",
        "黄金", "白银", "原油", "商品", "期货", "外汇", "汇率",
        "美元", "人民币", "欧元", "日元",
    )
    return any(marker in text for marker in markers)


def needs_slot_extraction(intent: str, query: str) -> bool:
    """确定槽位工具的候选边界；模型在候选范围内生成原生 tool_calls。"""
    if intent == "asset_allocation":
        return True
    if _has_non_stock_market_scope(query):
        return False
    if intent == "market_query":
        return _has_explicit_stock_reference(query)
    if intent == "stock_recommendation":
        return not needs_stock_screening(query)
    return False


class SupervisorAgent(BaseFinanceAgent):
    """监督者 Agent —— 根据问题生成最小必要任务计划。"""

    agent_name: str = "supervisor"

    def __init__(self, shared_memory=None, checkpointer=None):
        super().__init__(shared_memory=shared_memory, checkpointer=checkpointer)
        self._intent_chain = None
        self._zero_shot_classifier = None

    def _get_tools(self) -> list:
        return []

    def _get_system_prompt(self) -> str:
        return _SUPERVISOR_PROMPT

    @property
    def intent_chain(self):
        """轻量模型多意图分类链。"""
        if self._intent_chain is None:
            prompt = ChatPromptTemplate.from_messages([
                ("system", _SUPERVISOR_PROMPT),
                (
                    "human",
                    "近期对话：\n{context}\n\n"
                    "是否存在等待补充的资产配置任务：{pending_allocation}\n\n"
                    "当前用户输入：{message}\n\n请输出多意图分类JSON：",
                ),
            ])
            self._intent_chain = prompt | get_intent_model() | StrOutputParser()
        return self._intent_chain

    @property
    def zero_shot_classifier(self) -> ZeroShotIntentClassifier:
        if self._zero_shot_classifier is None:
            self._zero_shot_classifier = ZeroShotIntentClassifier(
                INTENT_ZERO_SHOT_MODEL,
                max_length=INTENT_MAX_LENGTH,
                score_threshold=INTENT_SCORE_THRESHOLD,
                device=INTENT_DEVICE,
                cache_dir=INTENT_MODEL_CACHE_DIR,
            )
        return self._zero_shot_classifier

    def _predict_zero_shot(
        self, message: str, context: str, pending_allocation: bool
    ) -> Dict[str, Any]:
        return self.zero_shot_classifier.predict(message, context, pending_allocation)

    def _submit_shadow_prediction(
        self,
        message: str,
        context: str,
        pending_allocation: bool,
        primary: Dict[str, Any],
        primary_latency_ms: float,
    ) -> None:
        """Evaluate zero-shot NLI without changing the primary classification."""
        def run() -> None:
            try:
                shadow = self._predict_zero_shot(message, context, pending_allocation)
                primary_labels = sorted(
                    str(item.get("intent", ""))
                    for item in primary.get("intents", [])
                    if isinstance(item, dict)
                )
                shadow_labels = sorted(
                    str(item.get("intent", ""))
                    for item in shadow.get("intents", [])
                    if isinstance(item, dict)
                )
                _LOGGER.info("intent_shadow %s", json.dumps({
                    "primary_labels": primary_labels,
                    "shadow_labels": shadow_labels,
                    "matched": primary_labels == shadow_labels,
                    "primary_latency_ms": primary_latency_ms,
                    "shadow_latency_ms": shadow.get("latency_ms"),
                }, ensure_ascii=False))
            except Exception as exc:
                _LOGGER.warning("intent_shadow_unavailable error=%s", exc)

        _SHADOW_EXECUTOR.submit(run)

    def classify_intents(
        self,
        message: str,
        context: str = "",
        pending_allocation: bool = False,
    ) -> Dict[str, Any]:
        """调用轻量模型分类，校验并合并同类意图。"""
        source = "zero_shot" if INTENT_CLASSIFIER_MODE == "zero_shot" else "model"
        classification_started = time.perf_counter()
        if INTENT_CLASSIFIER_MODE == "zero_shot":
            try:
                parsed = self._predict_zero_shot(message, context, pending_allocation)
            except Exception as exc:
                _LOGGER.warning("intent_zero_shot_unavailable error=%s", exc)
                parsed = {}
        else:
            try:
                raw = self.intent_chain.invoke({
                    "context": context or "无上下文",
                    "message": message,
                    "pending_allocation": "是" if pending_allocation else "否",
                })
                parsed = safe_parse_json(raw, {})
            except Exception as exc:
                _LOGGER.warning("intent_model_unavailable error=%s", exc)
                parsed = {}

            if (
                INTENT_CLASSIFIER_MODE == "shadow"
                and hasattr(self, "_zero_shot_classifier")
            ):
                self._submit_shadow_prediction(
                    message,
                    context,
                    pending_allocation,
                    parsed,
                    round((time.perf_counter() - classification_started) * 1000, 2),
                )

        def merge_valid(payload: Any, classifier_source: str) -> dict[str, dict[str, Any]]:
            merged_items: dict[str, dict[str, Any]] = {}
            raw_intents = payload.get("intents", []) if isinstance(payload, dict) else []
            if not isinstance(raw_intents, list):
                return merged_items
            for raw_item in raw_intents:
                if not isinstance(raw_item, dict):
                    continue
                candidate = dict(raw_item)
                intent = str(candidate.get("intent", "")).strip()
                if classifier_source == "zero_shot" and intent in _NLI_MODE_DEFAULTS:
                    candidate["execution_mode"] = _NLI_MODE_DEFAULTS[intent]
                item = normalize_intent_item(candidate, message)
                if item is None:
                    continue
                confidence_floor = (
                    0.0 if classifier_source == "zero_shot" else _CONFIDENCE_THRESHOLD
                )
                if item["confidence"] < confidence_floor:
                    continue
                intent = item["intent"]
                if intent in merged_items:
                    if item["query"] not in merged_items[intent]["query"]:
                        merged_items[intent]["query"] += "；" + item["query"]
                    merged_items[intent]["confidence"] = max(
                        merged_items[intent]["confidence"], item["confidence"],
                    )
                else:
                    merged_items[intent] = item
            return merged_items

        merged = merge_valid(parsed, source)
        if not merged and source != "zero_shot":
            try:
                parsed = self._predict_zero_shot(message, context, pending_allocation)
                source = "zero_shot"
                merged = merge_valid(parsed, source)
            except Exception as exc:
                _LOGGER.warning("intent_zero_shot_unavailable error=%s", exc)

        if not merged:
            source = "safe_fallback"
            fallback = normalize_intent_item({
                "intent": "casual_chat",
                "query": message,
                "confidence": 0.0,
                "reason": "意图分类服务暂不可用",
                "execution_mode": "conversation",
            }, message)
            assert fallback is not None
            merged = {"casual_chat": fallback}
            finance_related = False
        else:
            finance_related = bool(
                parsed.get("finance_related")
                if isinstance(parsed, dict) and "finance_related" in parsed
                else any(intent != "casual_chat" for intent in merged)
            )
        order = {name: index for index, name in enumerate(_INTENTS)}
        intents = sorted(merged.values(), key=lambda item: order[item["intent"]])
        print(
            "[Intent Classification] "
            + ", ".join(f"{item['intent']}={item['confidence']:.2f}" for item in intents)
            + f" | source={source}",
            flush=True,
        )
        return {
            "intents": intents,
            "finance_related": finance_related,
            "intent_source": source,
        }

    def plan_tasks(
        self,
        message: str,
        context: str = "",
        pending_allocation: bool = False,
    ) -> Dict[str, Any]:
        """把多意图确定性映射为共享数据工作流。"""
        classified = self.classify_intents(message, context, pending_allocation)
        modes = {
            str(item.get("execution_mode", ""))
            for item in classified["intents"]
        }
        requested: set[str] = set()
        if "security_analysis" in modes:
            requested.update({"data_fetch", "fundamental_analysis"})
        if modes & {"candidate_search", "security_comparison"}:
            requested.update({"data_fetch", "fundamental_analysis"})
        if "allocation" in modes:
            requested.update({
                "data_fetch", "fundamental_analysis", "asset_allocation",
            })
        if "conversation" in modes:
            requested.add("casual_chat")
        requested.add("compliance")
        allowed = [
            "slot_extraction", "data_fetch", "fundamental_analysis",
            "asset_allocation", "casual_chat", "compliance",
        ]
        classified["task_plan"] = [step for step in allowed if step in requested]
        classified["reason"] = "识别并编排全部有效意图"
        return classified

    def chat(self, query: str, context: str = "", finance_related: bool = True) -> str:
        """仅处理拆分后的理财闲聊子请求。"""
        if not finance_related:
            return "我主要协助处理投资理财、证券行情、选股研究和资产配置问题。你可以从这些方面继续问我。"
        prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                "你是有同理心且审慎的理财交流助手。只回应给定的闲聊子请求，"
                "可以讨论投资情绪、经验、心态和一般金融知识；不要查询或编造行情数据，"
                "不要推荐具体证券，不要生成个人资产配置方案。回答简洁自然。",
            ),
            ("human", "近期对话：\n{context}\n\n闲聊子请求：{query}"),
        ])
        return (prompt | get_supervisor_chat_model() | StrOutputParser()).invoke({
            "context": context or "无上下文",
            "query": query,
        }).strip()

    def decide_slot_tool_calls(
        self,
        detected_intents: List[Dict[str, Any]],
        slot_tool: BaseTool,
        context: str = "",
        pending_allocation: bool = False,
    ) -> List[Dict[str, Any]]:
        """使用轻量模型原生 tool_calls 决定哪些子意图需要槽位提取。"""
        prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                "你是金融工作流的工具调用决策器，不回答问题，也不重新分类。"
                "只允许调用 extract_finance_slots。资产配置必须调用；具体个股行情、"
                "财务、基本面和明确股票比较需要调用；板块/行业/概念行情、主题选股、"
                "泛化候选搜索和闲聊不得调用。同一意图最多调用一次。工具参数query"
                "必须原样使用该意图提供的子请求。无需工具时不得产生tool_calls。",
            ),
            (
                "human",
                "近期上下文：\n{context}\n\n等待资产配置补充：{pending}\n\n"
                "本轮意图：\n{intents}\n\n请决定是否调用工具。",
            ),
        ])
        response = (prompt | get_intent_model().bind_tools([slot_tool])).invoke({
            "context": context or "无上下文",
            "pending": "是" if pending_allocation else "否",
            "intents": json.dumps(detected_intents, ensure_ascii=False),
        })
        return [
            call for call in (getattr(response, "tool_calls", []) or [])
            if isinstance(call, dict)
        ]

    def handle(
        self,
        message: str,
        customer_id: str = "",
        chat_history: List[Dict[str, str]] | None = None,
        thread_id: str | None = None,
        memory_context: str = "",
    ) -> str:
        """监督者不直接回复用户，返回任务计划。"""
        result = self.plan_tasks(message, memory_context)
        return f"任务计划：{' → '.join(result['task_plan'])}\n原因：{result.get('reason', '')}"
