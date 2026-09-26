"""FAQ 文档索引 CLI 组合根。"""

from __future__ import annotations

import argparse

from finance_agent.infrastructure.settings import get_postgres_connection_factory
from finance_agent.infrastructure.persistence.postgres.faq_repository import PostgresFaqRepository
from finance_agent.domains.faq.embeddings import SentenceTransformerEmbeddingProvider
from finance_agent.domains.faq.indexer import index_faq_documents


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="finance_agent.cli.index_faq", description="投资规则 FAQ 索引",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    index = subparsers.add_parser("index", help="校验 docs/faq 并发布一个新索引版本")
    index.add_argument("--root", default="docs/faq", help="FAQ Markdown 目录")
    index.add_argument("--model-cache-dir", default=None, help="本地模型缓存目录")
    index.add_argument("--index-version", default=None, help="显式指定索引版本（默认自动生成）")
    args = parser.parse_args(argv)

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
    raise SystemExit(main())
