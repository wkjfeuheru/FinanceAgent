"""Guard application-layer ownership and prevent stale coordination paths."""

from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "finance_agent"


def test_orchestration_package_does_not_reexport_advisor_system() -> None:
    import finance_agent.orchestration as orchestration

    assert "AdvisorSystem" not in orchestration.__all__
    assert not hasattr(orchestration, "AdvisorSystem")

_CANONICAL_FILES = (
    "application/advisor.py",
    "application/turn_coordinator.py",
    "application/run_persistence.py",
    "application/async_recovery.py",
    "application/admin_service.py",
    "bootstrap.py",
)
_LEGACY_FILES = (
    "orchestration/advisor.py",
    "orchestration/runtime/turn.py",
    "orchestration/runtime/persistence.py",
    "orchestration/runtime/recovery.py",
    "orchestration/bootstrap.py",
    "admin/service.py",
)
_LEGACY_IMPORTS = (
    "finance_agent.orchestration.advisor",
    "finance_agent.orchestration.runtime.turn",
    "finance_agent.orchestration.runtime.persistence",
    "finance_agent.orchestration.runtime.recovery",
    "finance_agent.orchestration.bootstrap",
    "finance_agent.admin.service",
)


def test_application_coordination_uses_canonical_modules() -> None:
    missing = [
        path for path in _CANONICAL_FILES if not (PACKAGE_ROOT / path).is_file()
    ]
    stale = [
        path for path in _LEGACY_FILES if (PACKAGE_ROOT / path).exists()
    ]

    assert missing == [], "missing application modules: " + ", ".join(missing)
    assert stale == [], "legacy coordination modules remain: " + ", ".join(stale)


def test_production_and_tests_do_not_import_legacy_coordination_paths() -> None:
    offenders: list[str] = []
    roots = (PACKAGE_ROOT, REPO_ROOT / "tests")
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported = [node.module]
                else:
                    continue
                for module in imported:
                    if any(
                        module == legacy or module.startswith(legacy + ".")
                        for legacy in _LEGACY_IMPORTS
                    ):
                        offenders.append(
                            f"{path.relative_to(REPO_ROOT)} imports {module}"
                        )

    assert offenders == [], "stale coordination imports remain:\n" + "\n".join(
        offenders
    )
