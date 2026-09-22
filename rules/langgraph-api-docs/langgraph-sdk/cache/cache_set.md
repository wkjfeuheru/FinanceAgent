# cache_set

> **Function** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/cache/cache_set)

Set a value in the cache.

## Signature

```python
cache_set(
    key: str,
    value: Any,
    *,
    ttl: timedelta | None = None,
) -> None
```

## Description

Requires Agent Server runtime version 0.7.29 or later.

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `key` | `str` | Yes | The cache key. |
| `value` | `Any` | Yes | The value to cache (must be JSON-serializable). |
| `ttl` | `timedelta \| None` | No | Optional time-to-live. Capped at 1 day; ``None`` or zero defaults to 1 day. (default: `None`) |

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/cache.py#L74)