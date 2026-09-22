# StoreSearch

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/auth/types/StoreSearch)

Operation to search for items within a specified namespace hierarchy.

This dict is mutable — auth handlers can modify `namespace` to enforce
access scoping (e.g., prepending the user's identity).

## Signature

```python
StoreSearch()
```

## Extends

- `typing.TypedDict`

## Constructors

```python
__init__(
    namespace: tuple[str, ...],
    filter: dict[str, typing.Any] | None,
    limit: int,
    offset: int,
    query: str | None,
)
```

| Name | Type |
|------|------|
| `namespace` | `tuple[str, ...]` |
| `filter` | `dict[str, typing.Any] \| None` |
| `limit` | `int` |
| `offset` | `int` |
| `query` | `str \| None` |


## Properties

- `namespace`
- `filter`
- `limit`
- `offset`
- `query`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/auth/types.py#L879)