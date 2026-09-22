# CacheConfig

> **Class** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/schemas/CacheConfig)

## Signature

```python
CacheConfig()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    cache_keys: list[str],
    ttl_seconds: int,
    max_size: int,
)
```

| Name | Type |
|------|------|
| `cache_keys` | `list[str]` |
| `ttl_seconds` | `int` |
| `max_size` | `int` |


## Properties

- `cache_keys`
- `ttl_seconds`
- `max_size`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/schemas.py#L287)