# StorePut

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/auth/types/StorePut)

Operation to store, update, or delete an item in the store.

This dict is mutable — auth handlers can modify `namespace` to enforce
access scoping (e.g., prepending the user's identity).

## Signature

```python
StorePut()
```

## Extends

- `typing.TypedDict`

## Constructors

```python
__init__(
    namespace: tuple[str, ...],
    key: str,
    value: dict[str, typing.Any] | None,
    index: typing.Literal[False] | list[str] | None,
)
```

| Name | Type |
|------|------|
| `namespace` | `tuple[str, ...]` |
| `key` | `str` |
| `value` | `dict[str, typing.Any] \| None` |
| `index` | `typing.Literal[False] \| list[str] \| None` |


## Properties

- `namespace`
- `key`
- `value`
- `index`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/auth/types.py#L936)