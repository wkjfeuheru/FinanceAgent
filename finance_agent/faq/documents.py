"""投资规则 FAQ Markdown 的确定性解析。

约定：每个二级标题形如 ``## FAQ-001 标题``，一个标题到下一个标题之间的正文
构成一个分块。解析只做结构校验和切片，不调用模型，也不联网。
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from finance_agent.faq.contracts import FaqChunk

# 严格编号：FAQ- 加三位数字。
_FAQ_HEADING = re.compile(r"^##\s+(FAQ-\d{3})\s+(\S.*?)\s*$")
# 任何二级标题都用于识别文档结构，从而拒绝畸形编号。
_ANY_H2 = re.compile(r"^##\s+(.*)$")


class FaqDocumentError(ValueError):
    """FAQ 文档结构不符合约定。"""


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_faq_markdown(path: str | Path) -> list[FaqChunk]:
    """解析单个 FAQ 文件，返回按标题顺序排列的分块列表。"""
    file_path = Path(path)
    try:
        raw = file_path.read_text(encoding="utf-8")
    except OSError as exc:  # 文件缺失或不可读
        raise FaqDocumentError(f"cannot read faq document: {file_path}") from exc

    lines = raw.splitlines()
    sections: list[tuple[str, str, list[str]]] = []
    seen_ids: set[str] = set()
    current: tuple[str, str, list[str]] | None = None

    for line in lines:
        h2 = _ANY_H2.match(line)
        if h2 is not None:
            heading_body = h2.group(1).strip()
            strict = _FAQ_HEADING.match(line)
            if strict is None:
                if heading_body.startswith("FAQ"):
                    raise FaqDocumentError(
                        f"malformed faq heading in {file_path.name}: {heading_body!r}"
                    )
                # 非 FAQ 的二级标题不参与 FAQ 结构。
                current = None
                continue
            faq_id, title = strict.group(1), strict.group(2)
            if faq_id in seen_ids:
                raise FaqDocumentError(f"duplicate faq id in {file_path.name}: {faq_id}")
            seen_ids.add(faq_id)
            if current is not None:
                sections.append(current)
            current = (faq_id, title, [])
            continue
        if current is not None:
            current[2].append(line)

    if current is not None:
        sections.append(current)

    if not sections:
        raise FaqDocumentError(f"faq document has no FAQ sections: {file_path.name}")

    chunks: list[FaqChunk] = []
    for ordinal, (faq_id, title, body_lines) in enumerate(sections):
        body = "\n".join(body_lines).strip()
        if not body:
            raise FaqDocumentError(f"faq question has no answer in {file_path.name}: {faq_id}")
        embedding_text = f"问题：{title}\n答案：{body}"
        chunks.append(
            FaqChunk(
                faq_id=faq_id,
                question=title,
                answer=body,
                embedding_text=embedding_text,
                source_path=str(file_path),
                chunk_ordinal=ordinal,
                content_hash=_content_hash(embedding_text),
            )
        )
    return chunks
