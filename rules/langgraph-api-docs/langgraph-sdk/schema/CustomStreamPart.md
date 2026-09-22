# CustomStreamPart

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/schema/CustomStreamPart)

Stream part emitted for `stream_mode="custom"`.

## Signature

```python
CustomStreamPart()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    type: Literal['custom'],
    ns: list[str],
    data: Any,
)
```

| Name | Type |
|------|------|
| `type` | `Literal['custom']` |
| `ns` | `list[str]` |
| `data` | `Any` |


## Properties

- `type`
- `ns`
- `data`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/schema.py#L801)