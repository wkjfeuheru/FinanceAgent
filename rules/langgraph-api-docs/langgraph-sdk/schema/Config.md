# Config

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/schema/Config)

Configuration options for a call.

## Signature

```python
Config()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    tags: list[str],
    recursion_limit: int,
    configurable: dict[str, Any],
)
```

| Name | Type |
|------|------|
| `tags` | `list[str]` |
| `recursion_limit` | `int` |
| `configurable` | `dict[str, Any]` |


## Properties

- `tags`
- `recursion_limit`
- `configurable`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/schema.py#L185)