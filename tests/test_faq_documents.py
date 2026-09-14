"""FAQ Markdown 解析与索引发布的确定性契约。"""

from __future__ import annotations

from pathlib import Path

import pytest

from finance_agent.faq.documents import FaqDocumentError, parse_faq_markdown
from finance_agent.faq.indexer import FAQ_DOCUMENT_FILES, index_faq_documents, parse_faq_root

_INVESTMENT_BASICS = """# 投资基础知识 FAQ

## FAQ-001 什么是保证收益？

任何声称“保证收益”的私募或理财宣传都涉嫌违规。正规产品不会承诺保本保收益，
收益与风险始终匹配。

## FAQ-002 如何理解风险等级？

R1 至 R5 反映产品的风险由低到高，投资者需要选择与自身风险承受能力匹配的等级。
"""

_INVESTMENT_BASICS_WITH_DUP = """# 投资基础知识 FAQ

## FAQ-001 什么是保证收益？

保证收益的表述通常不合规。

## FAQ-001 重复编号

重复的 FAQ 编号必须被拒绝。
"""

_INVESTMENT_BASICS_EMPTY_ANSWER = """# 投资基础知识 FAQ

## FAQ-001 只有问题没有答案

## FAQ-002 有答案的问题

这是有效答案。
"""

_INVESTMENT_BASICS_BAD_ID = """# 投资基础知识 FAQ

## FAQ-1 编号格式错误

编号必须形如 FAQ-001。
"""


def _write(tmp_path, name: str, text: str):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_parser_keeps_each_faq_question_and_answer_in_one_chunk(tmp_path):
    """一个完整问答只生成一个分块，且保留问题与答案。"""
    path = _write(tmp_path, "investment-basics.md", _INVESTMENT_BASICS)

    chunks = parse_faq_markdown(path)

    assert [chunk.faq_id for chunk in chunks] == ["FAQ-001", "FAQ-002"]
    assert chunks[0].chunk_ordinal == 0
    assert chunks[1].chunk_ordinal == 1
    assert "保证收益" in chunks[0].content
    assert "R1 至 R5" in chunks[1].content
    assert chunks[0].source_path.endswith("investment-basics.md")
    assert chunks[0].content_hash


def test_parser_rejects_duplicate_faq_ids(tmp_path):
    path = _write(tmp_path, "investment-basics.md", _INVESTMENT_BASICS_WITH_DUP)

    with pytest.raises(FaqDocumentError):
        parse_faq_markdown(path)


def test_parser_rejects_heading_without_answer(tmp_path):
    path = _write(tmp_path, "investment-basics.md", _INVESTMENT_BASICS_EMPTY_ANSWER)

    with pytest.raises(FaqDocumentError):
        parse_faq_markdown(path)


def test_parser_rejects_malformed_heading_id(tmp_path):
    path = _write(tmp_path, "investment-basics.md", _INVESTMENT_BASICS_BAD_ID)

    with pytest.raises(FaqDocumentError):
        parse_faq_markdown(path)


class _FakeEmbedding:
    dimension = 512
    descriptor = "fake:512:normalized"

    def embed_documents(self, texts):
        return [[1.0] + [0.0] * 511 for _ in texts]


class _RecordingRepository:
    def __init__(self) -> None:
        self.published: list[dict] = []

    def publish_index(self, *, index_version, documents, chunks) -> None:
        self.published.append(
            {"index_version": index_version, "documents": list(documents), "chunks": list(chunks)}
        )


def test_repo_faq_documents_parse_and_publish_one_version():
    """仓库自带的三份 FAQ 必须可解析，并以单事务发布一个版本。"""
    docs_root = Path(__file__).resolve().parents[1] / "docs" / "faq"

    chunks = parse_faq_root(docs_root)
    repository = _RecordingRepository()
    version = index_faq_documents(
        docs_root,
        embedding_provider=_FakeEmbedding(),
        repository=repository,
        index_version="index-test",
    )

    assert version == "index-test"
    assert len(repository.published) == 1
    published = repository.published[0]
    assert len(published["chunks"]) == len(chunks)
    assert {chunk["faq_id"] for chunk in published["chunks"]} >= {"FAQ-001", "FAQ-101", "FAQ-201"}
    assert all(len(chunk["embedding"]) == 512 for chunk in published["chunks"])
    # 三份文件必须都已校验并参与解析。
    assert set(FAQ_DOCUMENT_FILES).issubset(
        {Path(document["source_path"]).name for document in published["documents"]}
    )

