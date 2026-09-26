"""全包静态守卫：模块里不得出现"未定义的全局名"。

历史上同一类缺陷出现过两次，而且都是**静默**降级，用户只看得到"像没上下文"：

- ``orchestration/routing/task_rewrite.py`` 用了 ``json`` 却没 import：任务改写器
  每次调用都抛 ``NameError``，被 ``except Exception`` 吞掉 → 指代性追问永远拿不到
  补全后的自包含任务描述；
- ``orchestration/memory.py`` 用了 ``logger`` 却没定义：画像读取失败时抛
  ``NameError`` 而不是回退空画像，整轮直接失败。

这类错误只在特定分支（异常路径、首次调用）才炸，靠人工 review 极易漏。这里用 AST
做一次静态扫描，把它变成常驻测试。
"""

from __future__ import annotations

import ast
import builtins
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "finance_agent"

#: 由运行环境注入的名字（静态扫描看不到赋值处）。
_RUNTIME_NAMES = {"__file__", "__name__", "__doc__", "__package__", "__spec__"}


def _annotation_node_ids(tree: ast.AST) -> set[int]:
    """收集"位于注解内部"的节点 id。

    ``from __future__ import annotations`` 让注解不参与求值，注解里出现但未导入的
    名字（如 ``pricing.py`` 的 ``Any``）不会在运行时报错，不属于本守卫的范围。
    """
    ids: set[int] = set()
    for node in ast.walk(tree):
        for target in (getattr(node, "annotation", None), getattr(node, "returns", None)):
            if target is None:
                continue
            for sub in ast.walk(target):
                ids.add(id(sub))
    return ids


def _unresolved_names(path: Path) -> list[str]:
    """返回该模块里被读取、但既未定义也非内建的全局名（保序、去重）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    annotation_ids = _annotation_node_ids(tree)

    defined = set(dir(builtins))
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                defined.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Name):
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                defined.add(node.id)
            elif isinstance(node.ctx, ast.Load) and id(node) not in annotation_ids:
                used.add(node.id)
        elif isinstance(node, ast.arg):
            defined.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            defined.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            defined.update(node.names)

    unresolved = used - defined - _RUNTIME_NAMES
    return sorted(unresolved)


def test_no_module_reads_an_undefined_global() -> None:
    offenders = [
        f"{path.relative_to(ROOT)} 读取了未定义的全局名: {', '.join(names)}"
        for path in sorted(PACKAGE.rglob("*.py"))
        for names in (_unresolved_names(path),)
        if names
    ]

    assert not offenders, "\n".join(offenders)
