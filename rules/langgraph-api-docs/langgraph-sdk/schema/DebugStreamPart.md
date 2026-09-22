# DebugStreamPart

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/schema/DebugStreamPart)

Stream part emitted for `stream_mode="debug"`.

## Signature

```python
DebugStreamPart()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    type: Literal['debug'],
    ns: list[str],
    data: DebugPayload,
)
```

| Name | Type |
|------|------|
| `type` | `Literal['debug']` |
| `ns` | `list[str]` |
| `data` | `DebugPayload` |


## Properties

- `type`
- `ns`
- `data`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/schema.py#L834)