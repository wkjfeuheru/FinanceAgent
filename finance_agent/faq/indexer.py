"""FAQ 索引构建：整批校验后一次性发布索引版本。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

from finance_agent.faq.contracts import FaqChunk
from finance_agent.faq.documents import parse_faq_markdown

FAQ_DOCUMENT_FILES = (
    "investment-basics.md",
    "risk-and-compliance.md",
    "trading-rules.md",
)


def _validate_root(root: Path) -> None:
    for name in FAQ_DOCUMENT_FILES:
        if not (root / name).is_file():
            raise FileNotFoundError(f"faq document missing: {root / name}")


def parse_faq_root(root: str | Path) -> list[FaqChunk]:
    """解析全部 FAQ 文件；任一文件不合规时整批失败。"""
    root_path = Path(root)
    _validate_root(root_path)

    chunks: list[FaqChunk] = []
    seen: set[str] = set()
    for name in FAQ_DOCUMENT_FILES:
        for chunk in parse_faq_markdown(root_path / name):
            if chunk.faq_id in seen:
                raise ValueError(f"duplicate faq id across documents: {chunk.faq_id}")
            seen.add(chunk.faq_id)
            chunks.append(chunk)
    return chunks


def index_faq_documents(
    root: str | Path,
    *,
    embedding_provider,
    repository,
    index_version: str | None = None,
) -> str:
    """校验、切分、向量化并发布一个索引版本，返回索引版本号。"""
    chunks = parse_faq_root(root)

    vectors = embedding_provider.embed_documents([chunk.content for chunk in chunks])
    if len(vectors) != len(chunks):
        raise ValueError("embedding provider returned an unexpected number of vectors")

    digest = hashlib.sha256(
        "|".join(f"{chunk.faq_id}:{chunk.content_hash}" for chunk in chunks).encode("utf-8")
    ).hexdigest()[:12]
    version = index_version or f"{embedding_provider.descriptor}:{digest}"

    documents = [
        {
            "document_id": str(uuid4()),
            "faq_id": chunk.faq_id,
            "source_path": chunk.source_path,
            "content_hash": chunk.content_hash,
        }
        for chunk in chunks
    ]
    chunk_rows = [
        {
            "chunk_id": str(uuid4()),
            "faq_id": chunk.faq_id,
            "source_path": chunk.source_path,
            "chunk_ordinal": chunk.chunk_ordinal,
            "content": chunk.content,
            "content_hash": chunk.content_hash,
            "embedding": vector,
        }
        for chunk, vector in zip(chunks, vectors)
    ]

    repository.publish_index(index_version=version, documents=documents, chunks=chunk_rows)
    return version
