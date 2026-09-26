from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_tests_are_classified_by_boundary() -> None:
    tests = ROOT / "tests"
    expected = {"unit", "integration", "contract", "e2e"}
    assert expected <= {path.name for path in tests.iterdir() if path.is_dir()}
    assert not list(tests.glob("test_*.py"))


def test_evals_are_split_into_scenarios_runners_and_baselines() -> None:
    evals = ROOT / "evals"
    expected = {"scenarios", "runners", "baselines"}
    assert expected <= {path.name for path in evals.iterdir() if path.is_dir()}
    assert {path.name for path in evals.glob("*.py")} <= {"__init__.py"}


def test_legacy_source_packages_are_removed() -> None:
    package = ROOT / "finance_agent"
    for legacy in (
        "admin", "data", "contracts", "tasks", "orchestrator", "research",
        "faq", "middleware", "product_research", "portfolio",
    ):
        assert not (package / legacy).exists(), f"legacy package remains: {legacy}"
