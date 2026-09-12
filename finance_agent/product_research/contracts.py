"""产品研究的稳定、可序列化契约。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


ProductAnalysisKind = Literal["single", "question", "deep_dive", "comparison"]
Freshness = Literal["fresh", "stale", "unknown"]
DataQuality = Literal["complete", "warning", "critical_missing"]
PersonalizationStatus = Literal["personalized", "research_candidate"]
SuitabilityStatus = Literal["matched", "unmatched", "unavailable", "not_evaluated"]


class _ProductModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProductResearchRequest(_ProductModel):
    """一次产品研究请求，不携带任何可变运行状态。"""

    kind: ProductAnalysisKind = "question"
    product_codes: list[str] = Field(default_factory=list)
    product_names: list[str] = Field(default_factory=list)
    profile: dict[str, Any] = Field(default_factory=dict)

    @field_validator("product_codes", "product_names")
    @classmethod
    def normalize_references(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


class ProductReference(_ProductModel):
    code: str
    name: str = ""


class ProductFieldEvidence(_ProductModel):
    """产品字段对应的原始事实及新鲜度。"""

    field: str
    value: Any = None
    source: str = "postgresql"
    as_of: str = ""
    freshness: Freshness = "unknown"
    fact_id: str


class ProductSnapshot(_ProductModel):
    """一次研究使用的产品事实快照。"""

    code: str
    name: str = ""
    basic_info: dict[str, Any] = Field(default_factory=dict)
    fee: dict[str, Any] = Field(default_factory=dict)
    holdings: dict[str, Any] = Field(default_factory=dict)
    performance: dict[str, Any] = Field(default_factory=dict)
    evidences: dict[str, ProductFieldEvidence] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    restrictions: list[str] = Field(default_factory=list)


class ProductAssessment(_ProductModel):
    """单个产品的规则评估，不包含交易动作。"""

    code: str
    name: str = ""
    evidences: dict[str, ProductFieldEvidence] = Field(default_factory=dict)
    risk_level: str | None = None
    risk_source: str = ""
    suitability_status: SuitabilityStatus = "not_evaluated"
    suitability_reasons: list[str] = Field(default_factory=list)
    usable_for_comparison: bool = False
    missing_fields: list[str] = Field(default_factory=list)
    restrictions: list[str] = Field(default_factory=list)


class ProductResearchResult(_ProductModel):
    """产品专家对外暴露的强类型结果。"""

    schema_version: str = "product_research.v1"
    kind: ProductAnalysisKind
    product_codes: list[str] = Field(default_factory=list)
    assessments: list[ProductAssessment] = Field(default_factory=list)
    report: str = ""
    data_quality: DataQuality = "complete"
    personalization_status: PersonalizationStatus = "research_candidate"
    evidence_ids: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)
