# UvLockPackage

> **Class** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/uv_lock/UvLockPackage)

## Signature

```python
UvLockPackage(
    self,
    name: str,
    normalized_name: str,
    root: pathlib.Path,
    pyproject_path: pathlib.Path,
    raw_dependency_specs: object,
    raw_uv_tool: object,
    package_enabled: bool = False,
    dependency_names: tuple[str, ...] = (),
    workspace_dependencies: tuple[str, ...] = (),
)
```

## Constructors

```python
__init__(
    self,
    name: str,
    normalized_name: str,
    root: pathlib.Path,
    pyproject_path: pathlib.Path,
    raw_dependency_specs: object,
    raw_uv_tool: object,
    package_enabled: bool = False,
    dependency_names: tuple[str, ...] = (),
    workspace_dependencies: tuple[str, ...] = (),
) -> None
```

| Name | Type |
|------|------|
| `name` | `str` |
| `normalized_name` | `str` |
| `root` | `pathlib.Path` |
| `pyproject_path` | `pathlib.Path` |
| `raw_dependency_specs` | `object` |
| `raw_uv_tool` | `object` |
| `package_enabled` | `bool` |
| `dependency_names` | `tuple[str, ...]` |
| `workspace_dependencies` | `tuple[str, ...]` |


## Properties

- `name`
- `normalized_name`
- `root`
- `pyproject_path`
- `raw_dependency_specs`
- `raw_uv_tool`
- `package_enabled`
- `dependency_names`
- `workspace_dependencies`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/uv_lock.py#L31)