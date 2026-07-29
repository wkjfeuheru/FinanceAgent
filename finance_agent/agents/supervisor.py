"""监督者 Agent。

职责：根据用户当前问题选择需要执行的子 Agent，并给出执行顺序。

不处理具体业务，仅做编排决策。
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any, Callable, Dict, List

import requests

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import BaseTool

from finance_agent.agents.base import ProceduralAgent
from finance_agent.config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_INTENT_MAX_RETRIES,
    DEEPSEEK_INTENT_MODEL,
    DEEPSEEK_INTENT_TIMEOUT,
    get_supervisor_model,
)


_INTENT_CLASSIFIER_PROMPT = """你是金融工作流的多意图分类器，只分类当前用户消息，不回答问题。
近期上下文摘要只能用于解析“它、这些股票、继续配置”等指代，不得从上下文新增当前消息未表达的意图。
历史中出现预算、风险偏好、期限或配置任务，不代表本轮要求资产配置。
只有当前消息明确要求资金分配、仓位、权重、组合构建，或者 pending_allocation=true 且当前消息在补充待填字段时，才能输出 asset_allocation。
“最近AI行业有什么值得投资的股票，为我推荐几个”只能输出 stock_recommendation，execution_mode=candidate_search。

允许的意图与 execution_mode：
- market_query: security_analysis | market_overview
- stock_recommendation: candidate_search | security_comparison
- asset_allocation: allocation
- casual_chat: conversation

每个意图必须包含 intent、query、confidence、reason、evidence、execution_mode、requires_slot_extraction。
evidence 必须逐字摘自 current_message，不能来自上下文。query 只包含该意图对应的当前轮子请求。
当 confidence 小于 0.9 时，必须返回非空 clarification_question，提出一个简短、具体、可直接回答的问题；不得直接回答或执行业务。
pending_clarifications 仅用于理解用户对上一轮反问的回复。若用户在纠正候选意图，可按当前消息改为正确意图；若已明确，必须回传对应 clarification_id。
解析待澄清项时，query 应结合 original_query 与当前回复形成完整、可执行的子请求；不能重复其他已经完成的意图。
不得因为近期上下文重复输出已经完成的高置信度意图。
只输出 JSON 对象：{"intents": [...], "finance_related": true}。"""

_CLASSIFIER_MODES = {
    "market_query": {"security_analysis", "market_overview"},
    "stock_recommendation": {"candidate_search", "security_comparison"},
    "asset_allocation": {"allocation"},
    "casual_chat": {"conversation"},
}

_INTENT_CONFIDENCE_THRESHOLD = 0.9


class IntentClassificationError(RuntimeError):
    """DeepSeek 意图识别不可用或返回非法协议。"""


class DeepSeekIntentClassifier:
    """通过 DeepSeek OpenAI 兼容接口执行多轮上下文意图分类。"""

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout: float = 30,
        max_retries: int = 1,
        requester: Callable[..., Any] = requests.post,
    ) -> None:
        self.api_key = api_key.strip()
        self.model = model.strip()
        self.timeout = timeout
        self.max_retries = min(max(0, max_retries), 1)
        self.requester = requester

    @staticmethod
    def _validate(payload: Any, message: str) -> dict[str, Any]:
        if not isinstance(payload, dict) or not isinstance(payload.get("intents"), list):
            raise IntentClassificationError("DeepSeek 意图响应必须包含 intents 列表")
        raw_intents = payload["intents"]
        if not raw_intents:
            raise IntentClassificationError("DeepSeek 意图响应必须包含至少一个意图")
        valid: list[dict[str, Any]] = []
        for item in raw_intents:
            if not isinstance(item, dict):
                continue
            intent = str(item.get("intent", "")).strip()
            mode = str(item.get("execution_mode", "")).strip()
            evidence = str(item.get("evidence", "")).strip()
            if intent not in _CLASSIFIER_MODES:
                raise IntentClassificationError(f"DeepSeek 返回非法 intent: {intent}")
            if mode not in _CLASSIFIER_MODES[intent]:
                raise IntentClassificationError(
                    f"DeepSeek 返回非法 execution_mode: {mode}"
                )
            if not evidence or evidence not in message:
                continue
            try:
                confidence = float(item.get("confidence"))
            except (TypeError, ValueError):
                raise IntentClassificationError("DeepSeek 意图置信度必须是有限数值")
            if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                raise IntentClassificationError("DeepSeek 意图置信度必须位于 0 到 1")
            if (
                confidence < _INTENT_CONFIDENCE_THRESHOLD
                and not str(item.get("clarification_question", "")).strip()
            ):
                raise IntentClassificationError(
                    "低置信度意图必须包含 clarification_question"
                )
            valid.append(dict(item))
        if raw_intents and not valid:
            raise IntentClassificationError("DeepSeek 意图响应没有可验证的当前轮证据")
        return {
            "intents": valid,
            "finance_related": bool(payload.get("finance_related", False)),
        }

    def classify(
        self,
        message: str,
        context_summary: str = "",
        pending_allocation: bool = False,
        pending_fields: list[str] | None = None,
        pending_clarifications: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise IntentClassificationError("缺少 DEEPSEEK_API_KEY")
        request_input = {
            "current_message": message.strip(),
            "recent_context_summary": context_summary.strip(),
            "pending_allocation": bool(pending_allocation),
            "pending_fields": list(pending_fields or []),
            "pending_clarifications": dict(pending_clarifications or {}),
        }
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _INTENT_CLASSIFIER_PROMPT},
                {"role": "user", "content": json.dumps(request_input, ensure_ascii=False)},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        error: Exception | None = None
        for _attempt in range(self.max_retries + 1):
            try:
                response = self.requester(
                    "https://api.deepseek.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                return self._validate(parsed, message)
            except Exception as exc:
                error = exc
        raise IntentClassificationError(f"DeepSeek 意图识别失败：{error}") from error


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
        "evidence": str(item.get("evidence", "")).strip(),
        "execution_mode": mode,
        "requires_slot_extraction": bool(
            _EXECUTION_MODES[intent].get(mode, False)
        ),
        "clarification_question": str(
            item.get("clarification_question", "")
        ).strip(),
        "clarification_id": str(item.get("clarification_id", "")).strip(),
        "clarification_ids": list(dict.fromkeys(
            [
                str(value).strip()
                for value in (
                    item.get("clarification_ids", [])
                    if isinstance(item.get("clarification_ids", []), list)
                    else []
                )
                if str(value).strip()
            ]
            + ([str(item.get("clarification_id", "")).strip()]
               if str(item.get("clarification_id", "")).strip() else [])
        )),
    }


def requires_slot_extraction(intent_plan: Dict[str, Any]) -> bool:
    """Authorize slot extraction only from a validated supervisor plan."""
    intent = str(intent_plan.get("intent", ""))
    mode = str(intent_plan.get("execution_mode", ""))
    return bool(
        intent_plan.get("requires_slot_extraction")
        and _EXECUTION_MODES.get(intent, {}).get(mode) is True
    )


class SupervisorAgent(ProceduralAgent):
    """监督者 Agent —— 根据问题生成最小必要任务计划。"""

    agent_name: str = "supervisor"

    def __init__(self, shared_memory=None, checkpointer=None):
        super().__init__(shared_memory=shared_memory)
        self._checkpointer = checkpointer
        self._intent_classifier = None

    def _get_tools(self) -> list:
        return []

    def _get_system_prompt(self) -> str:
        return _SUPERVISOR_PROMPT

    @property
    def intent_classifier(self) -> DeepSeekIntentClassifier:
        if self._intent_classifier is None:
            self._intent_classifier = DeepSeekIntentClassifier(
                api_key=DEEPSEEK_API_KEY,
                model=DEEPSEEK_INTENT_MODEL,
                timeout=DEEPSEEK_INTENT_TIMEOUT,
                max_retries=DEEPSEEK_INTENT_MAX_RETRIES,
            )
        return self._intent_classifier

    def _classify_with_deepseek(
        self,
        message: str,
        context_summary: str,
        pending_allocation: bool,
        pending_fields: list[str],
        pending_clarifications: dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        args = (message, context_summary, pending_allocation, pending_fields)
        if pending_clarifications:
            return self.intent_classifier.classify(*args, pending_clarifications)
        return self.intent_classifier.classify(*args)

    def classify_intents(
        self,
        message: str,
        context_summary: str = "",
        pending_allocation: bool = False,
        pending_fields: list[str] | None = None,
        pending_clarifications: dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """使用 DeepSeek 结合近期摘要识别并合并本轮全部意图。"""
        source = "deepseek"
        classification_error = False
        try:
            parsed = self._classify_with_deepseek(
                message,
                context_summary,
                pending_allocation,
                list(pending_fields or []),
                pending_clarifications,
            )
        except Exception as exc:
            _LOGGER.warning("intent_deepseek_unavailable error=%s", exc)
            parsed = {}
            classification_error = True

        uncertain: list[dict[str, Any]] = []

        def merge_valid(payload: Any) -> dict[str, dict[str, Any]]:
            merged_items: dict[str, dict[str, Any]] = {}
            raw_intents = payload.get("intents", []) if isinstance(payload, dict) else []
            if not isinstance(raw_intents, list):
                return merged_items
            for raw_item in raw_intents:
                if not isinstance(raw_item, dict):
                    continue
                candidate = dict(raw_item)
                intent = str(candidate.get("intent", "")).strip()
                item = normalize_intent_item(candidate, message)
                if item is None:
                    continue
                if item["confidence"] <= 0:
                    continue
                if item["confidence"] < _INTENT_CONFIDENCE_THRESHOLD:
                    uncertain.append(item)
                    continue
                intent = item["intent"]
                if intent in merged_items:
                    if item["query"] not in merged_items[intent]["query"]:
                        merged_items[intent]["query"] += "；" + item["query"]
                    merged_items[intent]["confidence"] = max(
                        merged_items[intent]["confidence"], item["confidence"],
                    )
                    merged_items[intent]["clarification_ids"] = list(dict.fromkeys(
                        merged_items[intent].get("clarification_ids", [])
                        + item.get("clarification_ids", [])
                    ))
                else:
                    merged_items[intent] = item
            return merged_items

        merged = merge_valid(parsed)
        if classification_error:
            source = "classification_error"
            merged = {}
            finance_related = False
            uncertain = []
        elif not merged and not uncertain:
            source = "classification_error"
            finance_related = False
        else:
            finance_related = bool(
                parsed.get("finance_related")
                if isinstance(parsed, dict) and "finance_related" in parsed
                else any(intent != "casual_chat" for intent in merged)
            )
        if uncertain and source != "classification_error":
            source = "clarification"
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
            "uncertain_intents": uncertain,
            "finance_related": finance_related,
            "intent_source": source,
        }

    def plan_tasks(
        self,
        message: str,
        context_summary: str = "",
        pending_allocation: bool = False,
        pending_fields: list[str] | None = None,
        pending_clarifications: dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """把多意图确定性映射为共享数据工作流。"""
        classified = self.classify_intents(
            message, context_summary, pending_allocation, pending_fields,
            pending_clarifications,
        )
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
