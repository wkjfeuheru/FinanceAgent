# ThreadTTLConfig

> **Class** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/schemas/ThreadTTLConfig)

Configure a default TTL for checkpointed data within threads.

## Signature

```python
ThreadTTLConfig()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    strategy: Literal['delete', 'keep_latest'],
    default_ttl: float | None,
    sweep_interval_minutes: int | None,
    sweep_limit: int | None,
)
```

| Name | Type |
|------|------|
| `strategy` | `Literal['delete', 'keep_latest']` |
| `default_ttl` | `float \| None` |
| `sweep_interval_minutes` | `int \| None` |
| `sweep_limit` | `int \| None` |


## Properties

- `strategy`
- `default_ttl`
- `sweep_interval_minutes`
- `sweep_limit`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/schemas.py#L109)