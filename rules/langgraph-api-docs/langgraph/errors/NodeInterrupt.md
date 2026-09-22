# NodeInterrupt

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/errors/NodeInterrupt)

Raised by a node to interrupt execution.

## Signature

```python
NodeInterrupt(
    self,
    value: Any,
    id: str | None = None,
)
```

## Extends

- `GraphInterrupt`

## Constructors

```python
__init__(
    self,
    value: Any,
    id: str | None = None,
) -> None
```

| Name | Type |
|------|------|
| `value` | `Any` |
| `id` | `str \| None` |


## ⚠️ Deprecated

NodeInterrupt is deprecated. Please use [`interrupt`][langgraph.types.interrupt] instead.

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/errors.py#L110)