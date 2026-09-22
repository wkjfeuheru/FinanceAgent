# UvLockPlan

> **Class** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/uv_lock/UvLockPlan)

## Signature

```python
UvLockPlan(
    self,
    project_root: pathlib.Path,
    pyproject_path: pathlib.Path,
    uv_lock_path: pathlib.Path,
    target: UvLockPackage,
    target_root: pathlib.Path,
    install_order: tuple[UvLockPackage, ...],
    container_roots: dict[pathlib.Path, pathlib.PurePosixPath],
    working_dir: str,
    all_workspace_roots: frozenset[pathlib.Path] = frozenset(),
)
```

## Constructors

```python
__init__(
    self,
    project_root: pathlib.Path,
    pyproject_path: pathlib.Path,
    uv_lock_path: pathlib.Path,
    target: UvLockPackage,
    target_root: pathlib.Path,
    install_order: tuple[UvLockPackage, ...],
    container_roots: dict[pathlib.Path, pathlib.PurePosixPath],
    working_dir: str,
    all_workspace_roots: frozenset[pathlib.Path] = frozenset(),
) -> None
```

| Name | Type |
|------|------|
| `project_root` | `pathlib.Path` |
| `pyproject_path` | `pathlib.Path` |
| `uv_lock_path` | `pathlib.Path` |
| `target` | `UvLockPackage` |
| `target_root` | `pathlib.Path` |
| `install_order` | `tuple[UvLockPackage, ...]` |
| `container_roots` | `dict[pathlib.Path, pathlib.PurePosixPath]` |
| `working_dir` | `str` |
| `all_workspace_roots` | `frozenset[pathlib.Path]` |


## Properties

- `project_root`
- `pyproject_path`
- `uv_lock_path`
- `target`
- `target_root`
- `install_order`
- `container_roots`
- `working_dir`
- `all_workspace_roots`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/uv_lock.py#L52)