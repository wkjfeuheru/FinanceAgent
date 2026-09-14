"""FAQ 索引 CLI。

用法::

    python -m finance_agent.faq index --root docs/faq --model-cache-dir .cache/models
"""

from __future__ import annotations

import argparse
import sys

from finance_agent.config import get_postgres_connection_factory
from finance_agent.faq.embeddings import SentenceTransformerEmbeddingProvider
from finance_agent.faq.indexer import index_faq_documents
from finance_agent.faq.repository import PostgresFaqRepository


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="finance_agent.faq", description="投资规则 FAQ 索引")
    subparsers = parser.add_subparsers(dest="command", required=True)

    index = subparsers.add_parser("index", help="校验 docs/faq 并发布一个新索引版本")
    index.add_argument("--root", default="docs/faq", help="FAQ Markdown 目录")
    index.add_argument("--model-cache-dir", default=None, help="本地模型缓存目录")
    index.add_argument("--index-version", default=None, help="显式指定索引版本（默认自动生成）")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command != "index":
        return 2

    embedding = SentenceTransformerEmbeddingProvider(cache_dir=args.model_cache_dir)
    repository = PostgresFaqRepository(get_postgres_connection_factory())
    version = index_faq_documents(
        args.root,
        embedding_provider=embedding,
        repository=repository,
        index_version=args.index_version,
    )
    print(f"published faq index version: {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
