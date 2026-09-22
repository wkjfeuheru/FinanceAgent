# TTLConfig

> **Class** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/schemas/TTLConfig)

Configuration for TTL (time-to-live) behavior in the store.

## Signature

```python
TTLConfig()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    refresh_on_read: bool,
    default_ttl: float | None,
    sweep_interval_minutes: int | None,
)
```

| Name | Type |
|------|------|
| `refresh_on_read` | `bool` |
| `default_ttl` | `float \| None` |
| `sweep_interval_minutes` | `int \| None` |


## Properties

- `refresh_on_read`
- `default_ttl`
- `sweep_interval_minutes`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/schemas.py#L9)