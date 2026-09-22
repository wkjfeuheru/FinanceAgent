# ThreadTTL

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/auth/types/ThreadTTL)

Time-to-live configuration for a thread.

Matches the OpenAPI schema where TTL is represented as an object with
an optional strategy and a time value in minutes.

## Signature

```python
ThreadTTL()
```

## Extends

- `typing.TypedDict`

## Constructors

```python
__init__(
    strategy: typing.Literal['delete'],
    ttl: int,
)
```

| Name | Type |
|------|------|
| `strategy` | `typing.Literal['delete']` |
| `ttl` | `int` |


## Properties

- `strategy`
- `ttl`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/auth/types.py#L429)