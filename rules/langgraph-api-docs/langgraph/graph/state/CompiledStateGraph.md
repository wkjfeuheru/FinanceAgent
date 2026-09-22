# CompiledStateGraph

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/graph/state/CompiledStateGraph)

## Signature

```python
CompiledStateGraph(
    self,
    *,
    builder: StateGraph[StateT, ContextT, InputT, OutputT],
    schema_to_mapper: dict[type[Any], Callable[[Any], Any] | None],
    **kwargs: Any = {},
)
```

## Extends

- `Pregel[StateT, ContextT, InputT, OutputT]`
- `Generic[StateT, ContextT, InputT, OutputT]`

## Constructors

```python
__init__(
    self,
    *,
    builder: StateGraph[StateT, ContextT, InputT, OutputT],
    schema_to_mapper: dict[type[Any], Callable[[Any], Any] | None],
    **kwargs: Any = {},
) -> None
```

| Name | Type |
|------|------|
| `builder` | `StateGraph[StateT, ContextT, InputT, OutputT]` |
| `schema_to_mapper` | `dict[type[Any], Callable[[Any], Any] \| None]` |


## Properties

- `builder`
- `schema_to_mapper`

## Methods

- [`get_input_jsonschema()`](https://reference.langchain.com/python/langgraph/graph/state/CompiledStateGraph/get_input_jsonschema)
- [`get_output_jsonschema()`](https://reference.langchain.com/python/langgraph/graph/state/CompiledStateGraph/get_output_jsonschema)
- [`attach_node()`](https://reference.langchain.com/python/langgraph/graph/state/CompiledStateGraph/attach_node)
- [`attach_edge()`](https://reference.langchain.com/python/langgraph/graph/state/CompiledStateGraph/attach_edge)
- [`attach_branch()`](https://reference.langchain.com/python/langgraph/graph/state/CompiledStateGraph/attach_branch)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/graph/state.py#L1391)