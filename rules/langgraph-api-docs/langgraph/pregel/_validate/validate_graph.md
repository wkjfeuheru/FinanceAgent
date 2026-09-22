# validate_graph

> **Function** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/pregel/_validate/validate_graph)

## Signature

```python
validate_graph(
    nodes: Mapping[str, PregelNode],
    channels: dict[str, BaseChannel],
    managed: ManagedValueMapping,
    input_channels: str | Sequence[str],
    output_channels: str | Sequence[str],
    stream_channels: str | Sequence[str] | None,
    interrupt_after_nodes: All | Sequence[str],
    interrupt_before_nodes: All | Sequence[str],
) -> None
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/pregel/_validate.py#L13)