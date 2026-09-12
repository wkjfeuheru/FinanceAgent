"""监督者 Agent。

职责：根据用户当前问题选择需要执行的子 Agent，并给出执行顺序。

不处理具体业务，仅做编排决策。
"""

from __future__ import annotations

import json
import logging
import math
import time
from typing import Any, Callable, Dict, List

import requests

from finance_agent.agents.base import ProceduralAgent
from finance_agent.contracts.adapters import (
    dispatch_plan_to_legacy,
    normalize_dispatch_plan,
    task_plan_to_legacy,
)
from finance_agent.config import (
    INTENT_MODEL_API_KEY,
    INTENT_MODEL_BASE_URL,
    INTENT_MODEL_DEADLINE,
    INTENT_MODEL_MAX_RETRIES,
    INTENT_MODEL_MAX_TOKENS,
    INTENT_MODEL,
    INTENT_MODEL_TIMEOUT,
)
from finance_agent.middleware import OUTPUT_BLOCKED_RESPONSE, check_sensitive_words


_INTENT_CLASSIFIER_PROMPT = """你是金融工作流的多意图分类器，只分类当前用户消息，不回答问题。
近期上下文摘要只能用于解析“它、这些股票、继续配置”等指代，不得从上下文新增当前消息未表达的意图。
历史中出现预算、风险偏好、期限或配置任务，不代表本轮要求资产配置。
只有当前消息明确要求资金分配、仓位、权重、组合构建，或者 pending_allocation=true 且当前消息在补充待填字段时，才能输出 asset_allocation。
“最近AI行业有什么值得投资的股票，为我推荐几个”只能输出 stock_recommendation，execution_mode=candidate_search。

允许的意图与 execution_mode：
- market_insight: market_overview | market_sentiment | capital_flow
- stock_analysis: stock_analysis
- stock_recommendation: candidate_search | stock_comparison
- asset_allocation: allocation
- product_analysis: product_analysis
- casual_chat: conversation

market_insight 只回答大盘/指数/市场整体问题，绝不输出个股结论或推荐：
“今天大盘怎么样”用 market_overview；“市场情绪/赚钱效应/涨跌家数”用 market_sentiment；
“北向资金/外资动向”用 capital_flow。
stock_analysis 只回答具体个股的基本面/技术面/行情；stock_recommendation 负责选股与多股比较。

每个意图必须包含 intent、query、confidence、reason、evidence、execution_mode、requires_slot_extraction。
evidence 必须逐字摘自 current_message，不能来自上下文。query 只包含该意图对应的当前轮子请求。
当 confidence 小于 0.9 时，必须返回非空 clarification_question，提出一个简短、具体、可直接回答的问题；不得直接回答或执行业务。
pending_clarifications 仅用于理解用户对上一轮反问的回复。若用户在纠正候选意图，可按当前消息改为正确意图；若已明确，必须回传对应 clarification_id。
解析待澄清项时，query 应结合 original_query 与当前回复形成完整、可执行的子请求；不能重复其他已经完成的意图。
不得因为近期上下文重复输出已经完成的高置信度意图。
只输出 JSON 对象：{"intents": [...], "finance_related": true}。"""

_CLASSIFIER_MODES = {
    "market_insight": {"market_overview", "market_sentiment", "capital_flow"},
    "stock_analysis": {"stock_analysis"},
    "stock_recommendation": {"candidate_search", "stock_comparison"},
    "asset_allocation": {"allocation"},
    "product_analysis": {"product_analysis"},
    "casual_chat": {"conversation"},
}

_INTENT_CONFIDENCE_THRESHOLD = 0.9


class IntentClassificationError(RuntimeError):
    """DeepSeek 意图识别不可用或返回非法协议。"""

    def __init__(self, message: str, *, error_code: str, cause: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.cause = cause


class DeepSeekIntentClassifier:
    """通过 Qwen OpenAI 兼容接口执行多轮上下文意图分类。"""

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout: float = 30,
        max_retries: int = 1,
        max_tokens: int = 512,
        deadline: float = 15,
        base_url: str = INTENT_MODEL_BASE_URL,
        requester: Callable[..., Any] = requests.post,
    ) -> None:
        self.api_key = api_key.strip()
        self.model = model.strip()
        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))
        self.max_tokens = max(1, int(max_tokens))
        self.deadline = max(0.0, float(deadline))
        self.base_url = base_url.strip()
        self.requester = requester

    @staticmethod
    def _validate(payload: Any, message: str) -> dict[str, Any]:
        if not isinstance(payload, dict) or not isinstance(payload.get("intents"), list):
            raise IntentClassificationError(
                "意图响应必须包含 intents 列表",
                error_code="intent_protocol_error", cause="invalid_schema",
            )
        raw_intents = payload["intents"]
        if not raw_intents:
            raise IntentClassificationError(
                "意图响应必须包含至少一个意图",
                error_code="intent_protocol_error", cause="empty_intents",
            )
        valid: list[dict[str, Any]] = []
        for item in raw_intents:
            if not isinstance(item, dict):
                continue
            intent = str(item.get("intent", "")).strip()
            mode = str(item.get("execution_mode", "")).strip()
            evidence = str(item.get("evidence", "")).strip()
            if intent not in _CLASSIFIER_MODES:
                raise IntentClassificationError(
                    f"返回非法 intent: {intent}",
                    error_code="intent_protocol_error", cause="invalid_intent",
                )
            if mode not in _CLASSIFIER_MODES[intent]:
                raise IntentClassificationError(
                    f"返回非法 execution_mode: {mode}",
                    error_code="intent_protocol_error", cause="invalid_execution_mode",
                )
            if not evidence or evidence not in message:
                continue
            try:
                confidence = float(item.get("confidence"))
            except (TypeError, ValueError):
                raise IntentClassificationError(
                    "意图置信度必须是有限数值",
                    error_code="intent_protocol_error", cause="invalid_confidence",
                )
            if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                raise IntentClassificationError(
                    "意图置信度必须位于 0 到 1",
                    error_code="intent_protocol_error", cause="invalid_confidence",
                )
            if (
                confidence < _INTENT_CONFIDENCE_THRESHOLD
                and not str(item.get("clarification_question", "")).strip()
            ):
                raise IntentClassificationError(
                    "低置信度意图必须包含 clarification_question",
                    error_code="intent_protocol_error", cause="missing_clarification",
                )
            valid.append(dict(item))
        if raw_intents and not valid:
            raise IntentClassificationError(
                "意图响应没有可验证的当前轮证据",
                error_code="intent_protocol_error", cause="missing_evidence",
            )
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
            raise IntentClassificationError(
                "缺少意图模型 API key",
                error_code="intent_unavailable", cause="missing_api_key",
            )
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
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
        }
        started = time.monotonic()
        error: IntentClassificationError | None = None
        for _attempt in range(self.max_retries + 1):
            remaining = self.deadline - (time.monotonic() - started)
            if remaining <= 0:
                raise IntentClassificationError(
                    "意图分类超过总 deadline",
                    error_code="intent_unavailable", cause="deadline",
                ) from error
            try:
                response = self.requester(
                    self.base_url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                    timeout=min(self.timeout, remaining),
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                try:
                    parsed = json.loads(content)
                except (TypeError, json.JSONDecodeError) as exc:
                    raise IntentClassificationError(
                        "意图响应不是合法 JSON",
                        error_code="intent_protocol_error", cause="invalid_json",
                    ) from exc
                return self._validate(parsed, message)
            except IntentClassificationError as exc:
                error = exc
            except requests.Timeout as exc:
                error = IntentClassificationError(
                    str(exc), error_code="intent_unavailable", cause="timeout",
                )
            except requests.HTTPError as exc:
                error = IntentClassificationError(
                    str(exc), error_code="intent_unavailable", cause="http",
                )
            except requests.RequestException as exc:
                error = IntentClassificationError(
                    str(exc), error_code="intent_unavailable", cause="transport",
                )
            except Exception as exc:
                error = IntentClassificationError(
                    str(exc), error_code="intent_unavailable", cause="transport",
                )
        assert error is not None
        raise error


_INTENTS = ("market_insight", "stock_analysis", "stock_recommendation", "asset_allocation", "product_analysis", "casual_chat")
_EXECUTION_MODES = {
    "market_insight": {"market_overview": False, "market_sentiment": False, "capital_flow": False},
    "stock_analysis": {"stock_analysis": True},
    "stock_recommendation": {"candidate_search": False, "stock_comparison": True},
    "asset_allocation": {"allocation": True},
    "product_analysis": {"product_analysis": True},
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
            if intent in {"stock_analysis", "stock_recommendation"}
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


class ManagerAgent(ProceduralAgent):
    """总管 Agent —— 负责意图识别、路由和最终响应合成。"""

    agent_name: str = "supervisor"

    def __init__(self, checkpointer=None):
        super().__init__()
        self._checkpointer = checkpointer
        self._intent_classifier = None

    @property
    def intent_classifier(self) -> DeepSeekIntentClassifier:
        if self._intent_classifier is None:
            self._intent_classifier = DeepSeekIntentClassifier(
                api_key=INTENT_MODEL_API_KEY,
                model=INTENT_MODEL,
                timeout=INTENT_MODEL_TIMEOUT,
                max_retries=INTENT_MODEL_MAX_RETRIES,
                max_tokens=INTENT_MODEL_MAX_TOKENS,
                deadline=INTENT_MODEL_DEADLINE,
                base_url=INTENT_MODEL_BASE_URL,
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
        classification_error_details: dict[str, str] = {}
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
            classification_error_details = {
                "error_code": getattr(exc, "error_code", "intent_unavailable"),
                "cause": getattr(exc, "cause", "unknown"),
            }

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
        _LOGGER.info(
            "[Intent Classification] %s | source=%s",
            ", ".join(f"{item['intent']}={item['confidence']:.2f}" for item in intents),
            source,
        )
        return {
            "intents": intents,
            "uncertain_intents": uncertain,
            "finance_related": finance_related,
            "intent_source": source,
            "classification_error": classification_error_details,
        }

    def dispatch_tasks(self, state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """在单一总管节点内识别意图并生成轻量专家路由。"""
        message = str(state.get("user_message", ""))
        classified = self.classify_intents(
            message,
            str(state.get("memory_context", "")),
            bool(state.get("pending_allocation", False)),
            list(state.get("pending_fields", []) or []),
            state.get("pending_clarifications"),
        )
        plan = normalize_dispatch_plan(classified.get("intents", []), message)
        state["tasks"] = plan.tasks
        dispatch = dispatch_plan_to_legacy(plan)
        state["detected_intents"] = classified.get("intents", [])
        state["uncertain_intents"] = classified.get("uncertain_intents", [])
        state["finance_related"] = classified.get("finance_related", False)
        state["classification_error"] = classified.get("classification_error", {})
        state["task_dispatch"] = dispatch
        state["task_plan"] = task_plan_to_legacy(plan)
        return dispatch

    def synthesize_response(self, state: Dict[str, Any]) -> str:
        """按用户友好顺序合并专家结果，并附加风险提示。"""
        task_results = state.get("task_results", {}) or {}
        tasks = state.get("tasks", []) or []
        if task_results and tasks:
            sections = []
            for task in tasks:
                result = task_results.get(task.task_id)
                if not result:
                    continue
                if hasattr(result, "summary"):
                    content = result.summary
                    status = result.status.value
                else:
                    content = str(result.get("summary", result.get("content", ""))).strip()
                    status = str(result.get("status", "success"))
                if content:
                    sections.append(content)
                elif status in {"failed", "degraded", "timeout", "blocked"}:
                    sections.append(f"{task.intent.value if task.intent else task.task_id}：暂无可用数据。")
            response = "\n\n".join(sections).strip()
            if response:
                if check_sensitive_words(response):
                    response = OUTPUT_BLOCKED_RESPONSE
                elif "风险提示" not in response:
                    response += "\n\n### 风险提示\n以上内容仅供参考，不构成投资建议。投资有风险，决策需谨慎。"
                state["agent_response"] = response
                return response
        results = state.get("intent_results", {}) or {}
        sections = []
        for intent in ("casual_chat", "market_insight", "stock_analysis", "stock_recommendation", "product_analysis", "asset_allocation"):
            result = results.get(intent, {})
            if not isinstance(result, dict):
                continue
            content = str(result.get("content", "")).strip()
            if content:
                sections.append(content)
            elif result.get("status") in {"error", "degraded"}:
                sections.append(f"{intent}：暂无可用数据。")
        response = "\n\n".join(sections).strip()
        if not response:
            response = str(state.get("agent_response", "")).strip() or "暂时无法生成回复。"
        # 输出侧合规校验：命中敏感词则整体拦截
        if check_sensitive_words(response):
            response = OUTPUT_BLOCKED_RESPONSE
        elif "风险提示" not in response:
            response += "\n\n### 风险提示\n以上内容仅供参考，不构成投资建议。投资有风险，决策需谨慎。"
        state["agent_response"] = response
        return response


