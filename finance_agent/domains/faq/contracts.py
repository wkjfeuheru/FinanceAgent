"""FAQ 检索的强类型契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class FaqChunk(BaseModel):
    """一个完整问答对应的索引分块。"""

    faq_id: str
    question: str
    answer: str
    embedding_text: str
    source_path: str
    chunk_ordinal: int
    content_hash: str


class FaqSearchMatch(BaseModel):
    """一条可引用的 FAQ 证据。"""

    faq_id: str
    chunk_id: str
    score: float
    index_version: str
    source_path: str
    question: str
    answer: str


class FaqSearchResult(BaseModel):
    """检索结果：只有可靠命中才进入 matches。"""

    status: Literal["found", "not_found"]
    matches: list[FaqSearchMatch] = Field(default_factory=list)
