# CachePolicy

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/types/CachePolicy)

Configuration for caching nodes.

## Signature

```python
CachePolicy(
    self,
    *,
    key_func: KeyFuncT = default_cache_key,
    ttl: int | None = None,
)
```

## Extends

- `Generic[KeyFuncT]`

## Constructors

```python
__init__(
    self,
    *,
    key_func: KeyFuncT = default_cache_key,
    ttl: int | None = None,
) -> None
```

| Name | Type |
|------|------|
| `key_func` | `KeyFuncT` |
| `ttl` | `int \| None` |


## Properties

- `key_func`
- `ttl`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/types.py#L518)