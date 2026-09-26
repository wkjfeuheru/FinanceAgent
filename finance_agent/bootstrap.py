"""AdvisorSystem 的启动依赖容器（Task 3）。

此前重量级依赖（checkpointer、审计仓储、记忆、分类器、运行状态、FAQ/异步任务/
量化网关）散落在 ``AdvisorSystem.__init__`` 与三个 ``_get_*`` 惰性方法里，构造
顺序、缓存位置与失败处理各写一遍。这里把**构造**收敛到一个容器：``__init__``
一次性取用，``_get_*`` 惰性方法复用餐器提供的构建器。

容器不做缓存（缓存仍由 ``AdvisorSystem`` 的实例字段持有），因此测试用
``object.__new__`` 构造的实例不依赖容器也能工作——构建器是可在无容器时直接调用的
静态方法。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class AdvisorDependencies:
    """AdvisorSystem 的一组已解析依赖（唯一构造入口）。"""

    budgets: Any
    checkpointer: Any
    business_store: Any
    run_state: Any
    memory: Any
    classifier: Any
    audit: Any

    @classmethod
    def build(cls) -> "AdvisorDependencies":
        """按生产装配顺序解析全部重量级依赖。"""
        from finance_agent.infrastructure.settings import get_checkpoint_saver
        from finance_agent.orchestration.budgets import RunBudgets
        from finance_agent.orchestration.memory import AgentMemoryContext
        from finance_agent.infrastructure.redis.memory import RedisMemoryStore
        from finance_agent.orchestration.persistence_database import get_database
        from finance_agent.infrastructure.checkpoint.run_state import RunStateStore
        from finance_agent.orchestration.routing.intent import IntentClassifier
        from finance_agent.infrastructure.persistence.postgres.audit_repository import PostgresAuditStore

        checkpointer = get_checkpoint_saver()
        business_store = get_database()
        return cls(
            budgets=RunBudgets.from_config(),
            checkpointer=checkpointer,
            business_store=business_store,
            run_state=RunStateStore(
                checkpointer=checkpointer, business_store=business_store,
            ),
            memory=AgentMemoryContext(
                store=RedisMemoryStore(), checkpointer=checkpointer,
            ),
            classifier=IntentClassifier(),
            audit=PostgresAuditStore.from_config(),
        )

    # ── 惰性构建器（供 _get_* 在无容器实例上回退复用）──────────────────

    @staticmethod
    def build_faq_embedding_provider():
        """FAQ 向量化提供者（检索与合规受信判定共用；模型首次调用才加载）。"""
        from finance_agent.domains.faq.embeddings import SentenceTransformerEmbeddingProvider

        return SentenceTransformerEmbeddingProvider()

    @staticmethod
    def build_faq_retriever(embedding_provider: Any = None):
        from finance_agent.infrastructure.settings import get_postgres_connection_factory
        from finance_agent.infrastructure.persistence.postgres.faq_repository import PostgresFaqRepository
        from finance_agent.domains.faq.retriever import FaqRetriever

        return FaqRetriever(
            PostgresFaqRepository(get_postgres_connection_factory()),
            embedding_provider or AdvisorDependencies.build_faq_embedding_provider(),
        )

    @staticmethod
    def build_async_run_repository():
        from finance_agent.infrastructure.settings import get_postgres_connection_factory
        from finance_agent.infrastructure.persistence.postgres.async_run_repository import PostgresAsyncRunRepository

        return PostgresAsyncRunRepository(get_postgres_connection_factory())

    @staticmethod
    def build_quant_gateway(async_repository: Any):
        from finance_agent.infrastructure.jobs.quant_gateway import CeleryQuantGateway

        return CeleryQuantGateway(async_repository=async_repository)


__all__ = ["AdvisorDependencies"]
