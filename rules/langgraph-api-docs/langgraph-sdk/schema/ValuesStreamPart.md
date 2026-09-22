# ValuesStreamPart

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/schema/ValuesStreamPart)

Stream part emitted for `stream_mode="values"`.

## Signature

```python
ValuesStreamPart()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    type: Literal['values'],
    ns: list[str],
    data: dict[str, Any],
    interrupts: list[dict[str, Any]],
)
```

| Name | Type |
|------|------|
| `type` | `Literal['values']` |
| `ns` | `list[str]` |
| `data` | `dict[str, Any]` |
| `interrupts` | `list[dict[str, Any]]` |


## Properties

- `type`
- `ns`
- `data`
- `interrupts`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/schema.py#L733)