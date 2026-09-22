# draw_graph

> **Function** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/pregel/_draw/draw_graph)

Get the graph for this Pregel instance.

## Signature

```python
draw_graph(
    config: RunnableConfig,
    *,
    nodes: dict[str, PregelNode],
    specs: dict[str, BaseChannel | ManagedValueSpec],
    input_channels: str | Sequence[str],
    interrupt_after_nodes: All | Sequence[str],
    interrupt_before_nodes: All | Sequence[str],
    trigger_to_nodes: Mapping[str, Sequence[str]],
    checkpointer: Checkpointer,
    subgraphs: dict[str, Graph],
    limit: int = 250,
) -> Graph
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `config` | `RunnableConfig` | Yes | The configuration to use for the graph. |
| `subgraphs` | `dict[str, Graph]` | Yes | The subgraphs to include in the graph. |
| `checkpointer` | `Checkpointer` | Yes | The checkpointer to use for the graph. |

## Returns

`Graph`

The graph for this Pregel instance.

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/pregel/_draw.py#L42)