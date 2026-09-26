"""PostgreSQL store classes have one canonical domain-specific module each."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_legacy_aggregate_module_is_retired():
    assert not (REPO_ROOT / "finance_agent" / "data" / "postgres_stores.py").exists()


def test_store_classes_live_in_their_focused_adapter_modules():
    from finance_agent.infrastructure.persistence.postgres.auth_store import PostgresAuthStore as AuthStore
    from finance_agent.infrastructure.persistence.postgres.business_store import (
        PostgresBusinessStore as BusinessStore,
        load_checkpoint_with_legacy_fallback,
    )
    from finance_agent.infrastructure.persistence.postgres.portfolio_store import PostgresPortfolioStore
    from finance_agent.infrastructure.persistence.postgres.product_store import PostgresProductLibrary

    assert AuthStore.__module__.endswith(".auth_store")
    assert BusinessStore.__module__.endswith(".business_store")
    assert PostgresPortfolioStore.__module__.endswith(".portfolio_store")
    assert PostgresProductLibrary.__module__.endswith(".product_store")
    assert callable(load_checkpoint_with_legacy_fallback)


def test_store_classes_are_defined_in_their_own_adapter_modules():
    from finance_agent.infrastructure.persistence.postgres.auth_store import PostgresAuthStore
    from finance_agent.infrastructure.persistence.postgres.business_store import PostgresBusinessStore
    from finance_agent.infrastructure.persistence.postgres.portfolio_store import PostgresPortfolioStore
    from finance_agent.infrastructure.persistence.postgres.product_store import PostgresProductLibrary

    assert PostgresAuthStore.__module__ == "finance_agent.infrastructure.persistence.postgres.auth_store"
    assert PostgresBusinessStore.__module__ == "finance_agent.infrastructure.persistence.postgres.business_store"
    assert PostgresPortfolioStore.__module__ == "finance_agent.infrastructure.persistence.postgres.portfolio_store"
    assert PostgresProductLibrary.__module__ == "finance_agent.infrastructure.persistence.postgres.product_store"
