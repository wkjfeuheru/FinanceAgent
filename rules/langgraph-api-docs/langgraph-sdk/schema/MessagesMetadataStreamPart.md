# MessagesMetadataStreamPart

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/schema/MessagesMetadataStreamPart)

Stream part emitted for message metadata (`messages/metadata`).

## Signature

```python
MessagesMetadataStreamPart()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    type: Literal['messages/metadata'],
    ns: list[str],
    data: dict[str, Any],
)
```

| Name | Type |
|------|------|
| `type` | `Literal['messages/metadata']` |
| `ns` | `list[str]` |
| `data` | `dict[str, Any]` |


## Properties

- `type`
- `ns`
- `data`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/schema.py#L779)