"""Guard canonical persistence, job-adapter and operational CLI ownership."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "finance_agent"


def test_persistence_jobs_and_cli_use_target_directories() -> None:
    required = (
        "infrastructure/persistence/__init__.py",
        "infrastructure/persistence/postgres/__init__.py",
        "infrastructure/persistence/postgres/connection.py",
        "infrastructure/persistence/postgres/transaction.py",
        "infrastructure/persistence/postgres/migrations.py",
        "infrastructure/persistence/postgres/schema.py",
        "infrastructure/persistence/postgres/auth_store.py",
        "infrastructure/persistence/postgres/business_store.py",
        "infrastructure/persistence/postgres/portfolio_store.py",
        "infrastructure/persistence/postgres/product_store.py",
        "infrastructure/persistence/postgres/runtime_repository.py",
        "infrastructure/persistence/postgres/research_repository.py",
        "infrastructure/persistence/postgres/faq_repository.py",
        "infrastructure/persistence/postgres/async_run_repository.py",
        "infrastructure/redis/__init__.py",
        "infrastructure/redis/memory.py",
        "infrastructure/checkpoint/__init__.py",
        "infrastructure/checkpoint/run_state.py",
        "infrastructure/jobs/__init__.py",
        "infrastructure/jobs/celery_app.py",
        "infrastructure/jobs/quant_gateway.py",
        "infrastructure/jobs/quant_tasks.py",
        "infrastructure/jobs/resume.py",
        "cli/__init__.py",
    )
    retired = (
        "celery_app.py",
        "tasks",
        "data/postgres_auth_store.py",
        "data/postgres_business_store.py",
        "data/postgres_faq_repository.py",
        "data/postgres_migrations.py",
        "data/postgres_portfolio_store.py",
        "data/postgres_product_store.py",
        "data/postgres_repository.py",
        "data/postgres_schema.py",
        "data/postgres_store_base.py",
        "data/postgres_stores.py",
        "data/postgres_transaction.py",
        "orchestration/runtime/quant.py",
        "orchestration/runtime/resume.py",
        "orchestration/runtime/run_state.py",
    )
    missing = [path for path in required if not (PACKAGE_ROOT / path).is_file()]
    stale = [path for path in retired if (PACKAGE_ROOT / path).exists()]

    assert missing == [], "missing canonical persistence/job modules: " + ", ".join(missing)
    assert stale == [], "retired persistence/job modules remain: " + ", ".join(stale)


def test_operational_commands_are_owned_by_cli_package() -> None:
    commands = (
        "bootstrap_admin.py",
        "diagnose_schema_drift.py",
        "index_faq.py",
        "replay_research_run.py",
        "verify_portfolio_live.py",
    )
    missing = [name for name in commands if not (PACKAGE_ROOT / "cli" / name).is_file()]
    stale = [name for name in commands if (REPO_ROOT / "tools" / name).exists()]

    assert missing == [], "missing canonical CLI commands: " + ", ".join(missing)
    assert stale == [], "legacy tools commands remain: " + ", ".join(stale)
