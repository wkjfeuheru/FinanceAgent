# swr

> **Function** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/cache/swr)

Load a cached value using stale-while-revalidate semantics.

This helper is server-side only and is intended for caching internal async
dependencies such as auth or metadata lookups.

## Signature

```python
swr(
    key: str,
    loader: Callable[[], Awaitable[T]],
    *,
    fresh_for: timedelta | None = None,
    max_age: timedelta | None = None,
    model: type[T] | None = None,
) -> SWRResult[T]
```

## Description

Semantics:
- cache miss: await ``loader()``, store the value, return it
- fresh hit (age < fresh_for): return the cached value
- stale hit (fresh_for <= age < max_age): return the cached value
  immediately and trigger a best-effort background refresh
- expired (age >= max_age): await ``loader()``, store the value, return it

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `key` | `str` | Yes | Cache key. |
| `loader` | `Callable[[], Awaitable[T]]` | Yes | Async callable that fetches the value on miss/revalidation. |
| `fresh_for` | `timedelta \| None` | No | How long a cached value is considered fresh (no revalidation). Defaults to ``timedelta(0)`` so every access triggers a background revalidate while still returning the cached value instantly. Values above :data:`MAX_CACHE_TTL` are clamped to the backend maximum. (default: `None`) |
| `max_age` | `timedelta \| None` | No | Total lifetime of a cached entry. After this, the next access blocks on the loader. Defaults to :data:`MAX_CACHE_TTL` (24 h by default). Values above :data:`MAX_CACHE_TTL` are clamped to the backend maximum. (default: `None`) |
| `model` | `type[T] \| None` | No | Optional Pydantic model class. When provided, values are serialized via ``model_dump(mode="json")`` before storage and deserialized via ``model.model_validate()`` on read. (default: `None`) |

## Returns

`SWRResult[T]`

class:`SWRResult` with ``.value``, ``.status``, and an async

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/cache.py#L93)