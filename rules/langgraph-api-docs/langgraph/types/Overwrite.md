# Overwrite

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/types/Overwrite)

Bypass a reducer and write the wrapped value directly to a `BinaryOperatorAggregate` channel.

Receiving multiple `Overwrite` values for the same channel in a single super-step
will raise an `InvalidUpdateError`.

!!! example

    ```python
    from typing import Annotated
    import operator
    from langgraph.graph import StateGraph
    from langgraph.types import Overwrite

    class State(TypedDict):
        messages: Annotated[list, operator.add]

    def node_a(state: TypedDict):
        # Normal update: uses the reducer (operator.add)
        return {"messages": ["a"]}

    def node_b(state: State):
        # Overwrite: bypasses the reducer and replaces the entire value
        return {"messages": Overwrite(value=["b"])}

    builder = StateGraph(State)
    builder.add_node("node_a", node_a)
    builder.add_node("node_b", node_b)
    builder.set_entry_point("node_a")
    builder.add_edge("node_a", "node_b")
    graph = builder.compile()

    # Without Overwrite in node_b, messages would be ["START", "a", "b"]
    # With Overwrite, messages is just ["b"]
    result = graph.invoke({"messages": ["START"]})
    assert result == {"messages": ["b"]}
    ```

## Signature

```python
Overwrite(
    self,
    value: Any,
    type: Literal['__overwrite__'] = '__overwrite__',
)
```

## Constructors

```python
__init__(
    self,
    value: Any,
    type: Literal['__overwrite__'] = '__overwrite__',
) -> None
```

| Name | Type |
|------|------|
| `value` | `Any` |
| `type` | `Literal['__overwrite__']` |


## Properties

- `value`
- `type`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/types.py#L937)