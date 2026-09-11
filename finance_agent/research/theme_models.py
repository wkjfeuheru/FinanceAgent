"""主题候选池治理的不可变领域模型。"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


_CODE = re.compile(r"^(?:60\d{4}|00\d{4}|30\d{4}|68\d{4}|8\d{5}|4\d{5})$")


class ThemeLead(BaseModel):
    """外部来源提供的待审核主题线索，不能自行生效。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid4()))
    theme_id: str
    stock_code: str
    industry: str = ""
    source_name: str
    source_class: Literal["official", "licensed_classification", "public_lead"]
    source_uri: str
    evidence_excerpt: str
    evidence_hash: str
    discovered_at: datetime

    @field_validator("stock_code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        if not _CODE.fullmatch(value.strip()):
            raise ValueError("无效股票代码")
        return value.strip()

    @field_validator("theme_id", "source_name", "source_uri", "evidence_excerpt", "evidence_hash")
    @classmethod
    def require_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("主题线索必填字段不能为空")
        return value.strip()

    @classmethod
    def evidence_digest(cls, source_uri: str, excerpt: str) -> str:
        return hashlib.sha256(f"{source_uri}\n{excerpt}".encode("utf-8")).hexdigest()


class ThemeMembership(BaseModel):
    """经审核后的成员关系；只有 active 且未到期者可被筛选。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    theme_id: str
    stock_code: str
    industry: str = ""
    status: Literal["pending", "active", "expired", "rejected"]
    evidence_expires_at: datetime
    lead_id: str
    created_at: datetime
    activated_at: datetime | None = None

