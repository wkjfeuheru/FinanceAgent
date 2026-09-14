"""领域意图分类器（原 Supervisor 的分类职责）。

只负责“属于哪个业务领域”，不再承担任务生成或响应拼装——那两项分别由
Root Graph 的路由（``orchestrator/root_graph.py``）与合规出口
（``orchestrator/compliance.py``）承担。分类协议错误必须显式上报，不得静默猜测。
"""

from __future__ import annotations

import json
import logging
import math
import time
from typing import Any, Callable, Dict

import requests

from finance_agent.config import (
    INTENT_MODEL,
    INTENT_MODEL_API_KEY,
    INTENT_MODEL_BASE_URL,
    INTENT_MODEL_DEADLINE,
    INTENT_MODEL_MAX_RETRIES,
    INTENT_MODEL_MAX_TOKENS,
    INTENT_MODEL_TIMEOUT,
)

_INTENT_CLASSIFIER_PROMPT = """你是金融工作流的多意图分类器，只分类当前用户消息，不回答问题。
近期上下文摘要只能用于解析“它、这些股票”等指代，不得从上下文新增当前消息未表达的意图。
“最近AI行业有什么值得投资的股票，为我推荐几个”只能输出 stock_recommendation，execution_mode=candidate_search。

允许的意图与 execution_mode：
- market_insight: market_overview | market_sentiment | capital_flow | policy_impact
- stock_analysis: stock_analysis
- stock_recommendation: candidate_search | stock_comparison
- product_analysis: product_analysis
- casual_chat: conversation

market_insight 只回答大盘/指数/市场整体问题，绝不输出个股结论或推荐：
“今天大盘怎么样”用 market_overview；“市场情绪/赚钱效应/涨跌家数”用 market_sentiment；
“资金面/两融/融资融券/北向持仓”用 capital_flow；
“政策/新闻/消息面有什么动态、对市场有什么影响”用 policy_impact。
stock_analysis 只回答具体个股的基本面/技术面/行情；stock_recommendation 负责选股与多股比较。

每个意图必须包含 intent、query、confidence、reason、evidence、execution_mode、requires_slot_extraction。
evidence 必须逐字摘自 current_message，不能来自上下文。query 只包含该意图对应的当前轮子请求。
当 confidence 小于 0.9 时，必须返回非空 clarification_question，提出一个简短、具体、可直接回答的问题；不得直接回答或执行业务。
解析用户对上轮反问的回复时，query 应结合上下文形成完整、可执行的子请求；不能重复其他已经完成的意图。
不得因为近期上下文重复输出已经完成的高置信度意图。
只输出 JSON 对象：{"intents": [...], "finance_related": true}。"""

_CLASSIFIER_MODES = {
    "market_insight": {"market_overview", "market_sentiment", "capital_flow", "policy_impact"},
    "stock_analysis": {"stock_analysis"},
    "stock_recommendation": {"candidate_search", "stock_comparison"},
    "product_analysis": {"product_analysis"},
    "casual_chat": {"conversation"},
}

_INTENT_CONFIDENCE_THRESHOLD = 0.9


class IntentClassificationError(RuntimeError):
    """意图识别不可用或返回非法协议。"""

    def __init__(self, message: str, *, error_code: str, cause: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.cause = cause


class DeepSeekIntentClassifier:
    """通过 OpenAI 兼容接口执行多轮上下文意图分类。"""

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
    ) -> dict[str, Any]:
        if not self.api_key:
            raise IntentClassificationError(
                "缺少意图模型 API key",
                error_code="intent_unavailable", cause="missing_api_key",
            )
        request_input = {
            "current_message": message.strip(),
            "recent_context_summary": context_summary.strip(),
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


_INTENTS = ("market_insight", "stock_analysis", "stock_recommendation", "product_analysis", "casual_chat")
_EXECUTION_MODES = {
    "market_insight": {
        "market_overview": False, "market_sentiment": False,
        "capital_flow": False, "policy_impact": False,
    },
    "stock_analysis": {"stock_analysis": True},
    "stock_recommendation": {"candidate_search": False, "stock_comparison": True},
    "product_analysis": {"product_analysis": True},
    "casual_chat": {"conversation": False},
}
_LOGGER = logging.getLogger(__name__)


def normalize_intent_item(
    item: Dict[str, Any], fallback_query: str,
) -> Dict[str, Any] | None:
    """校验单条意图并补齐其可执行路由字段。"""
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


class IntentClassifier:
    """合并本轮全部意图，产出三领域路由所需的分类结果。"""

    def __init__(self, *, classifier: Any = None) -> None:
        self._intent_classifier = classifier

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

    def _classify_with_model(self, message: str, context_summary: str) -> Dict[str, Any]:
        return self.intent_classifier.classify(message, context_summary)

    def classify_intents(
        self,
        message: str,
        context_summary: str = "",
    ) -> Dict[str, Any]:
        """结合近期摘要识别并合并本轮全部意图。"""
        source = "deepseek"
        classification_error = False
        classification_error_details: dict[str, str] = {}
        try:
            parsed = self._classify_with_model(message, context_summary)
        except Exception as exc:
            _LOGGER.warning("intent_classifier_unavailable error=%s", exc)
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
            # 模型返回了 intents，但没有一条通过校验。必须标记分类失败，
            # 否则编排层只看到空字典会误判成功。
            source = "classification_error"
            finance_related = False
            classification_error_details = {
                "error_code": "intent_protocol_error",
                "cause": "no_valid_intents",
            }
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


__all__ = [
    "DeepSeekIntentClassifier",
    "IntentClassificationError",
    "IntentClassifier",
    "normalize_intent_item",
]
