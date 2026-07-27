"""Multilingual zero-shot multi-label intent classification runtime."""

from __future__ import annotations

import re
import time
from typing import Any, Callable


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
    """Lazy Transformers zero-shot classifier with stable internal intent names."""

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
        self, message: str, context: str, pending_allocation: bool
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
            [
                (segment, self._scores(segment, context, pending_allocation))
                for segment in segments
            ]
            if len(segments) > 1
            else []
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
            intents.append(
                {
                    "intent": intent,
                    "query": query,
                    "confidence": confidence,
                    "reason": "多语言 NLI 零样本分类",
                }
            )

        business_match = any(
            item["intent"] != "casual_chat" for item in intents
        )
        normalized = message.strip()
        return {
            "intents": intents,
            "finance_related": business_match
            or any(term in normalized for term in _FINANCIAL_TERMS),
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }
