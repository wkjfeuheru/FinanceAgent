# NodeCancelledError

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/errors/NodeCancelledError)

Raised when a node body raises ``asyncio.CancelledError`` itself.

``asyncio.CancelledError`` is a ``BaseException`` and the pregel runner
treats cancelled task futures as silent tear-down (e.g. when it stops
sibling tasks after a peer fails). That is the correct behaviour for
*framework-initiated* cancellation, but a user node that raises
``asyncio.CancelledError`` from its own body should surface as a node
failure, the same way any other exception would.

The retry layer converts user-raised ``asyncio.CancelledError`` into this
type so it flows through the normal error path and the run reports as
``error`` instead of silently succeeding.

## Signature

```python
NodeCancelledError(
    self,
    node: str,
    message: str | None = None,
)
```

## Extends

- `Exception`

## Constructors

```python
__init__(
    self,
    node: str,
    message: str | None = None,
) -> None
```

| Name | Type |
|------|------|
| `node` | `str` |
| `message` | `str \| None` |


## Properties

- `node`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/errors.py#L168)