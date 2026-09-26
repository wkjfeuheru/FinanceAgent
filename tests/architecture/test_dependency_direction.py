"""Guard the dependency direction between domains and orchestration."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_COMPUTATION_PREFIXES = (
    "finance_agent.orchestration",
    "finance_agent.api",
    "finance_agent.infrastructure",
    "langchain",
    "langgraph",
)
PIPELINE_SYMBOLS = (
    "ResearchPipeline",
    "ProductResearchPipeline",
    "NarrativeRenderer",
)
#: 专家工具不得直接依赖的确定性内核（应经 ``evaluation`` 封装层调用）。
EXPERT_FORBIDDEN_KERNEL = (
    "finance_agent.domains.research.rule_engine",
    "finance_agent.domains.research.snapshot_builder",
    "finance_agent.domains.research.scoring",
)

DOMAIN_ROOTS = (
    "research",
    "products",
    "portfolio",
    "faq",
    "market",
)

EXPERTS_ROOT = REPO_ROOT / "finance_agent" / "orchestration" / "experts"
ALLOWED_EXPERT_ROOT_FILES = {"base.py", "registry.py", "__init__.py"}


def _module_name(path: Path) -> str:
    relative = path.relative_to(REPO_ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _is_expert_path(path: Path) -> bool:
    return "expert" in path.relative_to(REPO_ROOT / "finance_agent" / "domains").parts


def _resolved_imports(tree: ast.AST, module_name: str) -> set[str]:
    package = module_name if module_name.endswith(".__init__") else module_name.rpartition(".")[0]
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".")
                base = parts[: max(0, len(parts) - node.level + 1)]
                if node.module:
                    base.extend(node.module.split("."))
                target = ".".join(base)
            else:
                target = node.module or ""
            if target:
                imports.add(target)
            imports.update(f"{target}.{alias.name}" for alias in node.names if target)
    return imports


def _domain_python_files() -> list[Path]:
    files: list[Path] = []
    for name in DOMAIN_ROOTS:
        root = REPO_ROOT / "finance_agent" / "domains" / name
        if root.is_dir():
            files.extend(sorted(root.rglob("*.py")))
    return files


def test_computation_modules_do_not_import_orchestration_api_or_adapters() -> None:
    offenders: list[str] = []
    for path in _domain_python_files():
        if _is_expert_path(path):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        module_name = _module_name(path)
        for imported in _resolved_imports(tree, module_name):
            if any(
                imported == prefix or imported.startswith(prefix + ".")
                for prefix in FORBIDDEN_COMPUTATION_PREFIXES
            ):
                offenders.append(f"{path.relative_to(REPO_ROOT)} imports {imported}")
            if imported.endswith(".expert") or ".expert." in imported:
                offenders.append(f"{path.relative_to(REPO_ROOT)} imports {imported}")
    assert offenders == [], "Computation modules must not depend on adapters or expert/:\n" + "\n".join(offenders)


def test_expert_adapters_may_import_langchain_and_expert_base() -> None:
    expert_files = [path for path in _domain_python_files() if _is_expert_path(path)]
    assert expert_files, "domains/*/expert/ must exist"
    for path in expert_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        module_name = _module_name(path)
        imported = _resolved_imports(tree, module_name)
        for symbol in PIPELINE_SYMBOLS:
            if any(item.endswith("." + symbol) or item == symbol for item in imported):
                raise AssertionError(f"{path.relative_to(REPO_ROOT)} imports pipeline symbol {symbol}")


def test_quant_tasks_do_not_import_orchestration() -> None:
    task_file = REPO_ROOT / "finance_agent" / "infrastructure" / "jobs" / "quant_tasks.py"
    assert task_file.is_file(), "canonical quant task module must exist"
    tree = ast.parse(task_file.read_text(encoding="utf-8"), filename=str(task_file))
    assert tree.body, "canonical quant task module must not be empty"
    offenders: list[str] = []
    for imported in _resolved_imports(tree, _module_name(task_file)):
        if imported == "finance_agent.orchestration" or imported.startswith(
            "finance_agent.orchestration."
        ):
            offenders.append(f"{task_file.relative_to(REPO_ROOT)} imports {imported}")
    assert offenders == [], "Tasks must not depend on orchestration:\n" + "\n".join(offenders)


def test_orchestration_experts_root_only_has_shared_shell() -> None:
    assert EXPERTS_ROOT.is_dir()
    present = {path.name for path in EXPERTS_ROOT.iterdir() if path.suffix == ".py"}
    extra = present - ALLOWED_EXPERT_ROOT_FILES
    missing = ALLOWED_EXPERT_ROOT_FILES - present
    assert extra == set(), f"orchestration/experts/ extra modules: {sorted(extra)}"
    assert missing == set(), f"orchestration/experts/ missing: {sorted(missing)}"
    assert not (EXPERTS_ROOT / "tools").exists(), "retired experts/tools/ must be gone"


def test_shared_compatibility_exports_and_product_tools_have_one_owner() -> None:
    shared_names = importlib.import_module("finance_agent.shared.name_matching")
    stock_expert = importlib.import_module("finance_agent.domains.research.expert")
    shared_contracts = importlib.import_module("finance_agent.shared.contracts")
    orchestration_contracts = importlib.import_module("finance_agent.orchestration.contracts")
    catalog = importlib.import_module("finance_agent.domains.products.expert.catalog")
    product_expert = importlib.import_module("finance_agent.domains.products.expert")

    assert stock_expert.name_match.match_names is shared_names.match_names
    assert orchestration_contracts.DomainOutcome.model_fields["pending_jobs"].annotation == list[
        shared_contracts.AsyncJobRef
    ]
    whitelist = product_expert.product_tools()
    assert catalog.query_product in whitelist
    assert catalog.list_products in whitelist


def test_expert_tools_reach_deterministic_kernel_only_via_evaluation() -> None:
    """专家工具不得绕过 ``evaluation`` 直接 import 确定性内核。

    ``evaluate_research`` 通过 ``evaluation.evaluate`` 组合规则引擎/快照/评分；
    这条边界让内核的实现细节（阈值、门禁、评分表）不向 expert 层泄露。
    """
    offenders: list[str] = []
    for path in _domain_python_files():
        if not _is_expert_path(path):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for imported in _resolved_imports(tree, _module_name(path)):
            for kernel in EXPERT_FORBIDDEN_KERNEL:
                if imported == kernel or imported.startswith(kernel + "."):
                    offenders.append(f"{path.relative_to(REPO_ROOT)} imports {imported}")
    assert offenders == [], "Expert tools must use evaluation.*, not the raw kernel:\n" + "\n".join(offenders)


def test_domain_registry_is_single_source_for_identity() -> None:
    """领域身份（枚举 + 顺序）唯一定义在 ``domains``，编排层只 re-export/复用。"""
    from finance_agent.domains.contracts import DOMAIN_ORDER, BusinessDomain as DomainEnum
    from finance_agent.domains.registry import DOMAIN_SPECS
    from finance_agent.orchestration.contracts import BusinessDomain as OrchestrationEnum
    from finance_agent.orchestration.graphs import supervisor

    assert DomainEnum is OrchestrationEnum, "orchestration.contracts 必须 re-export domains 枚举"
    assert set(DOMAIN_SPECS) == set(DomainEnum), "注册表必须覆盖全部领域"
    assert tuple(DOMAIN_SPECS[d].domain for d in DOMAIN_ORDER) == DOMAIN_ORDER
    assert supervisor._DOMAIN_ORDER == DOMAIN_ORDER, "supervisor 排序必须复用 domains 顺序"


def test_every_domain_spec_declares_a_loadable_prompt() -> None:
    """每个领域登记的提示词路径都必须存在且非空（防止外置后漏包/漏登记）。"""
    from finance_agent.domains.registry import DOMAIN_SPECS
    from finance_agent.shared.prompts import load_prompt

    for domain, spec in DOMAIN_SPECS.items():
        content = load_prompt(spec.prompt_path)
        assert content.strip(), f"{domain} 的 system prompt 为空：{spec.prompt_path}"


def test_expert_adapters_do_not_import_domain_registry() -> None:
    """``domains/registry.py`` 不得被 expert 实现反向 import（避免循环与职责倒挂）。"""
    offenders: list[str] = []
    for path in _domain_python_files():
        if not _is_expert_path(path):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for imported in _resolved_imports(tree, _module_name(path)):
            if imported.startswith("finance_agent.domains.registry"):
                offenders.append(f"{path.relative_to(REPO_ROOT)} imports {imported}")
    assert offenders == [], "expert 实现不应依赖领域注册表：\n" + "\n".join(offenders)
