# RetryPolicy

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/types/RetryPolicy)

Configuration for retrying nodes.

!!! version-added "Added in version 0.2.24"

## Signature

```python
RetryPolicy()
```

## Extends

- `NamedTuple`

## Properties

- `initial_interval`
- `backoff_factor`
- `max_interval`
- `max_attempts`
- `jitter`
- `retry_on`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/types.py#L416)