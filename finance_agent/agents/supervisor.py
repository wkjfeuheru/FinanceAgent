"""监督者 Agent。

职责：根据用户当前问题选择需要执行的子 Agent，并给出执行顺序。

不处理具体业务，仅做编排决策。
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from typing import Any, Callable, Dict, List

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import BaseTool

from finance_agent.agents.base import BaseFinanceAgent
from finance_agent.config import (
    INTENT_DEVICE,
    INTENT_MAX_LENGTH,
    INTENT_MODEL_CACHE_DIR,
    INTENT_SCORE_THRESHOLD,
    get_supervisor_model,
)


INTENT_LABELS = (
    "market_query",
    "stock_recommendation",
    "asset_allocation",
    "casual_chat",
)
CANDIDATE_LABELS = {
    "market_query": "查询股票、指数、板块或市场行情",
    "stock_recommendation": "推荐股票或判断某只股票是否值得买入",
    "asset_allocation": "根据金额、期限和风险偏好制定资产配置方案",
    "casual_chat": "一般理财知识、投资心态或非任务型金融交流",
}
HYPOTHESIS_TEMPLATE = "这段用户消息的意图是{}。"
_INTENT_ZERO_SHOT_MODEL = "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"
_SPLIT_PATTERN = re.compile(
    r"(?:[。！？!?；;\n]+|(?:，|,)?\s*(?:同时|另外|然后|顺便|并且|而且|再者)\s*)"
)
_FINANCIAL_TERMS = (
    "投资", "理财", "股票", "基金", "行情", "市场", "板块", "行业", "资产",
    "配置", "组合", "股价", "指数", "证券", "买入", "卖出", "仓位", "收益",
)


def split_intent_queries(message: str) -> list[str]:
    """Split explicit independent clauses, preserving the original on ambiguity."""
    text = (message or "").strip()
    if not text:
        return []
    parts = [part.strip(" ，,") for part in _SPLIT_PATTERN.split(text)]
    parts = [part for part in parts if len(part) >= 2]
    return parts if len(parts) > 1 else [text]


class ZeroShotIntentClassifier:
    """Lazy multilingual NLI classifier with stable internal intent names."""

    def __init__(
        self,
        model_name: str,
        max_length: int = 256,
        score_threshold: float = 0.5,
        device: int = -1,
        cache_dir: str | None = None,
        pipeline_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.model_name = model_name
        self.max_length = max_length
        self.score_threshold = score_threshold
        self.device = device
        self.cache_dir = cache_dir or None
        self._pipeline_factory = pipeline_factory
        self._pipeline = None

    def _load(self) -> None:
        if self._pipeline is not None:
            return
        if self._pipeline_factory is None:
            from transformers import pipeline

            self._pipeline_factory = pipeline
        kwargs: dict[str, Any] = {"model": self.model_name, "device": self.device}
        if self.cache_dir:
            kwargs["model_kwargs"] = {"cache_dir": self.cache_dir}
        self._pipeline = self._pipeline_factory("zero-shot-classification", **kwargs)

    @staticmethod
    def _input_text(message: str, context: str, pending_allocation: bool) -> str:
        pending = "是" if pending_allocation else "否"
        return f"[上下文] {context or '无'} [待补充配置] {pending} [当前输入] {message}"

    def _scores(
        self, message: str, context: str, pending_allocation: bool,
    ) -> dict[str, float]:
        self._load()
        result = self._pipeline(
            self._input_text(message, context, pending_allocation),
            list(CANDIDATE_LABELS.values()),
            multi_label=True,
            hypothesis_template=HYPOTHESIS_TEMPLATE,
            truncation=True,
            max_length=self.max_length,
        )
        label_to_intent = {label: intent for intent, label in CANDIDATE_LABELS.items()}
        scores = {intent: 0.0 for intent in INTENT_LABELS}
        for label, score in zip(result["labels"], result["scores"]):
            intent = label_to_intent.get(label)
            if intent is not None:
                scores[intent] = float(score)
        return scores

    def predict(
        self,
        message: str,
        context: str = "",
        pending_allocation: bool = False,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        whole = self._scores(message, context, pending_allocation)
        segments = split_intent_queries(message)
        segment_scores = (
            [(segment, self._scores(segment, context, pending_allocation)) for segment in segments]
            if len(segments) > 1 else []
        )
        intents: list[dict[str, Any]] = []
        for intent in INTENT_LABELS:
            matched = [
                (text, scores[intent])
                for text, scores in segment_scores
                if scores[intent] >= self.score_threshold
            ]
            confidence = max([whole[intent], *(score for _, score in matched)])
            if confidence < self.score_threshold:
                continue
            query = "；".join(text for text, _ in matched) if matched else message.strip()
            intents.append({
                "intent": intent,
                "query": query,
                "confidence": confidence,
                "reason": "多语言 NLI 零样本分类",
            })
        business_match = any(item["intent"] != "casual_chat" for item in intents)
        normalized = message.strip()
        return {
            "intents": intents,
            "finance_related": business_match or any(term in normalized for term in _FINANCIAL_TERMS),
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }


_SUPERVISOR_PROMPT = """你是金融投顾系统的监督者，负责根据已识别意图编排工作流。
不得重新解释用户原文来增加意图，也不得直接执行金融数据工具。
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
    if not math.isfinite(confidence):
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


def requires_slot_extraction(intent_plan: Dict[str, Any]) -> bool:
    """Authorize slot extraction only from a validated supervisor plan."""
    intent = str(intent_plan.get("intent", ""))
    mode = str(intent_plan.get("execution_mode", ""))
    return bool(
        intent_plan.get("requires_slot_extraction")
        and _EXECUTION_MODES.get(intent, {}).get(mode) is True
    )


class SupervisorAgent(BaseFinanceAgent):
    """监督者 Agent —— 根据问题生成最小必要任务计划。"""

    agent_name: str = "supervisor"

    def __init__(self, shared_memory=None, checkpointer=None):
        super().__init__(shared_memory=shared_memory, checkpointer=checkpointer)
        self._zero_shot_classifier = None

    def _get_tools(self) -> list:
        return []

    def _get_system_prompt(self) -> str:
        return _SUPERVISOR_PROMPT

    @property
    def zero_shot_classifier(self) -> ZeroShotIntentClassifier:
        if self._zero_shot_classifier is None:
            self._zero_shot_classifier = ZeroShotIntentClassifier(
                _INTENT_ZERO_SHOT_MODEL,
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

    def classify_intents(
        self,
        message: str,
        context: str = "",
        pending_allocation: bool = False,
    ) -> Dict[str, Any]:
        """使用固定多语言 NLI 分类器识别并合并本轮全部意图。"""
        source = "zero_shot"
        try:
            parsed = self._predict_zero_shot(message, context, pending_allocation)
        except Exception as exc:
            _LOGGER.warning("intent_zero_shot_unavailable error=%s", exc)
            parsed = {}

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
                if item["confidence"] < INTENT_SCORE_THRESHOLD:
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
        return (prompt | get_supervisor_model() | StrOutputParser()).invoke({
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
        response = (prompt | get_supervisor_model().bind_tools([slot_tool])).invoke({
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
