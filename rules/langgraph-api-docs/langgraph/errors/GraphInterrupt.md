# GraphInterrupt

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/errors/GraphInterrupt)

Raised when a subgraph is interrupted, suppressed by the root graph.
Never raised directly, or surfaced to the user.

## Signature

```python
GraphInterrupt(
    self,
    interrupts: Sequence[Interrupt] = (),
)
```

## Extends

- `GraphBubbleUp`

## Constructors

```python
__init__(
    self,
    interrupts: Sequence[Interrupt] = (),
) -> None
```

| Name | Type |
|------|------|
| `interrupts` | `Sequence[Interrupt]` |


---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/errors.py#L102)