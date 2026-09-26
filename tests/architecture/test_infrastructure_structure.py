"""Guard infrastructure-owned market-data, settings and model adapters."""

from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "finance_agent"


def _imported_modules(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.module:
        modules = [node.module]
        if node.module == "finance_agent":
            modules.extend(
                f"{node.module}.{alias.name}"
                for alias in node.names
                if alias.name == "infrastructure"
            )
        return modules
    return []


def test_from_import_infrastructure_is_resolved_as_dependency() -> None:
    node = ast.parse("from finance_agent import infrastructure").body[0]

    assert "finance_agent.infrastructure" in _imported_modules(node)


def test_infrastructure_owns_external_market_data_and_model_adapters() -> None:
    required = (
        "infrastructure/__init__.py",
        "infrastructure/settings.py",
        "infrastructure/llm/__init__.py",
        "infrastructure/llm/factory.py",
        "infrastructure/market_data/__init__.py",
        "infrastructure/market_data/providers.py",
        "infrastructure/market_data/provider_manager.py",
        "infrastructure/market_data/normalization.py",
        "infrastructure/market_data/quote_cache.py",
        "infrastructure/market_data/trading_calendar.py",
        "infrastructure/market_data/akshare_provider.py",
        "infrastructure/market_data/baostock_provider.py",
        "infrastructure/market_data/fuyao_mcp.py",
        "infrastructure/market_data/board_codes.py",
    )
    retired = (
        "config.py",
        "settings.py",
        "data/providers.py",
        "data/provider_manager.py",
        "data/normalization.py",
        "data/quote_cache.py",
        "data/trading_calendar.py",
        "data/akshare_provider.py",
        "data/baostock_provider.py",
        "data/fuyao_mcp.py",
        "data/board_codes.py",
    )
    missing = [path for path in required if not (PACKAGE_ROOT / path).is_file()]
    stale = [path for path in retired if (PACKAGE_ROOT / path).exists()]

    assert missing == [], "missing canonical infrastructure modules: " + ", ".join(missing)
    assert stale == [], "retired adapter modules remain: " + ", ".join(stale)


def test_domains_do_not_depend_on_infrastructure_or_retired_config_modules() -> None:
    retired = ("finance_agent.config", "finance_agent.settings")
    offenders: list[str] = []
    for root in (PACKAGE_ROOT, REPO_ROOT / "tests"):
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                modules = _imported_modules(node)
                for module in modules:
                    retired_import = any(
                        module == name or module.startswith(name + ".") for name in retired
                    )
                    domain_infrastructure = (
                        path.is_relative_to(PACKAGE_ROOT / "domains")
                        and "expert" not in path.relative_to(PACKAGE_ROOT / "domains").parts
                        and (module == "finance_agent.infrastructure" or module.startswith("finance_agent.infrastructure."))
                    )
                    if retired_import or domain_infrastructure:
                        offenders.append(f"{path.relative_to(REPO_ROOT)} imports {module}")

    assert offenders == [], "forbidden adapter dependencies remain:\n" + "\n".join(offenders)
