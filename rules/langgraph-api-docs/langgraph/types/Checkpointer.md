# Checkpointer

> **Type Alias** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/types/Checkpointer)

Type of the checkpointer to use for a subgraph.

- `True` enables persistent checkpointing for this subgraph.
- `False` disables checkpointing, even if the parent graph has a checkpointer.
- `None` inherits checkpointer from the parent graph.

## Signature

```python
Checkpointer = None | bool | BaseCheckpointSaver
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/types.py#L98)