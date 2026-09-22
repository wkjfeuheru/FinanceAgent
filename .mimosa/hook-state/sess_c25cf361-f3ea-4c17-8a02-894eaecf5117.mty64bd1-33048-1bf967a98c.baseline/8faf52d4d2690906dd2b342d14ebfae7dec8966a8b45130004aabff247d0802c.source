"""确定性股票研究的不可变领域契约。"""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


_STOCK_CODE_PATTERN = re.compile(
    r"^(?:60\d{4}|00\d{4}|30\d{4}|68\d{4}|8\d{5}|4\d{5})$"
)


class AnalysisKind(str, Enum):
    """支持的研究请求类型。"""

    SINGLE_STOCK = "single_stock"
    COMPARISON = "comparison"
    THEME_SCREENING = "theme_screening"


class Action(str, Enum):
    """风险优先决策矩阵可返回的行动结论。"""

    WATCH = "关注"
    WAIT = "观望"
    AVOID = "规避"
    INSUFFICIENT_DATA = "数据不足"


class AnalysisRequest(BaseModel):
    """一次研究执行所需的不可变、确定性输入。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: AnalysisKind
    stock_codes: list[str] = Field(default_factory=list)
    theme_id: str | None = None
    horizon: Literal["short", "medium", "long"] = "medium"
    indicators: list[str] = Field(default_factory=list)
    profile_complete: bool = False

    @model_validator(mode="before")
    @classmethod
    def normalize_and_validate_shape(cls, data: Any) -> Any:
        """规范代码并在模型边界校验不同请求类型的最小形态。"""
        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        seen: set[str] = set()
        codes: list[str] = []
        for raw_code in normalized.get("stock_codes", []) or []:
            code = str(raw_code).strip()
            if _STOCK_CODE_PATTERN.fullmatch(code) and code not in seen:
                seen.add(code)
                codes.append(code)
        normalized["stock_codes"] = codes
        normalized["theme_id"] = (
            str(normalized["theme_id"]).strip()
            if normalized.get("theme_id") is not None
            else None
        )

        kind = normalized.get("kind")
        kind_value = kind.value if isinstance(kind, AnalysisKind) else str(kind)
        if kind_value == AnalysisKind.SINGLE_STOCK.value and len(codes) != 1:
            raise ValueError("单股分析必须且只能包含一只股票")
        if kind_value == AnalysisKind.COMPARISON.value and len(codes) < 2:
            raise ValueError("股票比较至少需要两只股票")
        if kind_value == AnalysisKind.THEME_SCREENING.value and not normalized.get("theme_id"):
            raise ValueError("主题筛选必须提供 theme_id")
        return normalized

    def for_security(self, code: str) -> "AnalysisRequest":
        """收敛到单只标的的研究请求。

        结论的原子单位是单只标的：比较请求的单项结论按单股结论描述
        （``kind`` 转为 ``single_stock``），使每条结论都能独立评分、审计与
        展示。已经是该标的的单标的请求时返回自身。
        """
        normalized = str(code).strip()
        if self.kind is not AnalysisKind.COMPARISON and self.stock_codes == [normalized]:
            return self
        update: dict[str, Any] = {"stock_codes": [normalized]}
        if self.kind is AnalysisKind.COMPARISON:
            update["kind"] = AnalysisKind.SINGLE_STOCK
        return self.model_copy(update=update)


class AnalysisResult(BaseModel):
    """确定性研究产物的最小稳定外层契约。"""

    model_config = ConfigDict(extra="forbid")

    request: AnalysisRequest | None = None
    action: Action
    data_quality: Literal["complete", "warning", "critical_missing"]
    rule_version: str = ""
    scores: dict[str, float | None] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    personalization_status: Literal["personalized", "research_candidate"] = "research_candidate"
    restrictions: list[str] = Field(default_factory=list)
    narrative: str = ""
    report_mode: Literal["deterministic", "llm", "template_fallback"] = "deterministic"

    @model_validator(mode="after")
    def prevent_watch_with_critical_data(self) -> "AnalysisResult":
        """关键数据不足时不得给出关注结论。"""
        if self.data_quality == "critical_missing" and self.action is Action.WATCH:
            raise ValueError("关键数据缺失时不得输出关注结论")
        return self


class DataQuality(BaseModel):
    """快照级数据质量结论。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["complete", "warning", "critical_missing"] = "complete"
    missing_critical: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def is_critical(self) -> bool:
        return self.status == "critical_missing"


class QuoteSnapshot(BaseModel):
    """带来源信息的最新报价。"""

    model_config = ConfigDict(frozen=True, extra="allow")

    source: str = "unavailable"
    fetched_at: datetime | None = None
    fallback_from: str | None = None
    as_of: str = ""
    price: float | None = None


class SecuritySnapshot(BaseModel):
    """单只股票的标准化研究输入。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    basic_info: dict[str, Any] = Field(default_factory=dict)
    quote: QuoteSnapshot
    history: dict[str, Any] = Field(default_factory=dict)
    indicators: dict[str, Any] = Field(default_factory=dict)
    quality: DataQuality = Field(default_factory=DataQuality)


class MarketDataSnapshot(BaseModel):
    """一次请求使用的不可变市场数据快照。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request: AnalysisRequest
    securities: list[SecuritySnapshot]
    quality: DataQuality
