# GraphDrained

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/errors/GraphDrained)

Raised when a graph run exits early due to a drain request.

This indicates the graph stopped cooperatively at a superstep boundary
because `RunControl.request_drain()` was called (e.g., in response to
SIGTERM). The checkpoint is saved and the run can be resumed later.

## Signature

```python
GraphDrained(
    self,
    reason: str = 'shutdown',
)
```

## Extends

- `GraphBubbleUp`

## Constructors

```python
__init__(
    self,
    reason: str = 'shutdown',
) -> None
```

| Name | Type |
|------|------|
| `reason` | `str` |


## Properties

- `reason`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/errors.py#L54)