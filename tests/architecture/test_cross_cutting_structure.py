"""Guard canonical shared contracts and split safety-policy ownership."""

from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "finance_agent"


def test_shared_and_safety_modules_use_canonical_paths() -> None:
    required = (
        "shared/contracts.py",
        "shared/identifiers.py",
        "shared/serialization.py",
        "safety/detector.py",
        "safety/input_policy.py",
        "safety/output_policy.py",
        "orchestration/budgets.py",
    )
    legacy = (
        "contracts",
        "safety/content_filter.py",
    )
    missing = [path for path in required if not (PACKAGE_ROOT / path).is_file()]
    stale = [path for path in legacy if (PACKAGE_ROOT / path).exists()]

    assert missing == [], "missing canonical cross-cutting modules: " + ", ".join(missing)
    assert stale == [], "legacy cross-cutting modules remain: " + ", ".join(stale)


def test_source_and_tests_do_not_import_retired_contract_or_filter_modules() -> None:
    retired = (
        "finance_agent.contracts",
        "finance_agent.safety.content_filter",
    )
    offenders: list[str] = []
    for root in (PACKAGE_ROOT, REPO_ROOT / "tests"):
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules = [node.module]
                else:
                    continue
                for module in modules:
                    if any(module == name or module.startswith(name + ".") for name in retired):
                        offenders.append(f"{path.relative_to(REPO_ROOT)} imports {module}")

    assert offenders == [], "retired cross-cutting imports remain:\n" + "\n".join(offenders)
