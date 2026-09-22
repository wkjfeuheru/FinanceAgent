# UvLockWorkspace

> **Class** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/uv_lock/UvLockWorkspace)

## Signature

```python
UvLockWorkspace(
    self,
    raw_root_source_entries: object,
    packages_by_name: dict[str, UvLockPackage],
    packages_by_root: dict[pathlib.Path, UvLockPackage],
)
```

## Constructors

```python
__init__(
    self,
    raw_root_source_entries: object,
    packages_by_name: dict[str, UvLockPackage],
    packages_by_root: dict[pathlib.Path, UvLockPackage],
) -> None
```

| Name | Type |
|------|------|
| `raw_root_source_entries` | `object` |
| `packages_by_name` | `dict[str, UvLockPackage]` |
| `packages_by_root` | `dict[pathlib.Path, UvLockPackage]` |


## Properties

- `raw_root_source_entries`
- `packages_by_name`
- `packages_by_root`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/uv_lock.py#L45)