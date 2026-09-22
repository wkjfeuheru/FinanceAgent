# StateGraph

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/graph/state/StateGraph)

A graph whose nodes communicate by reading and writing to a shared state.

The signature of each node is `State -> Partial<State>`.

Each state key can optionally be annotated with a reducer function that
will be used to aggregate the values of that key received from multiple nodes.
The signature of a reducer function is `(Value, Value) -> Value`.

!!! warning

    `StateGraph` is a builder class and cannot be used directly for execution.
    You must first call `.compile()` to create an executable graph that supports
    methods like `invoke()`, `stream()`, `astream()`, and `ainvoke()`. See the
    `CompiledStateGraph` documentation for more details.

## Signature

```python
StateGraph(
    self,
    state_schema: type[StateT],
    context_schema: type[ContextT] | None = None,
    *,
    input_schema: type[InputT] | None = None,
    output_schema: type[OutputT] | None = None,
    **kwargs: Unpack[DeprecatedKwargs] = {},
)
```

## Description

!!! warning "`config_schema` Deprecated"
The `config_schema` parameter is deprecated in v0.6.0 and support will be removed in v2.0.0.
Please use `context_schema` instead to specify the schema for run-scoped context.

**Example:**

```python
from langchain_core.runnables import RunnableConfig
from typing_extensions import Annotated, TypedDict
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph
from langgraph.runtime import Runtime

def reducer(a: list, b: int | None) -> list:
    if b is not None:
        return a + [b]
    return a

class State(TypedDict):
    x: Annotated[list, reducer]

class Context(TypedDict):
    r: float

graph = StateGraph(state_schema=State, context_schema=Context)

def node(state: State, runtime: Runtime[Context]) -> dict:
    r = runtime.context.get("r", 1.0)
    x = state["x"][-1]
    next_value = x * r * (1 - x)
    return {"x": next_value}

graph.add_node("A", node)
graph.set_entry_point("A")
graph.set_finish_point("A")
compiled = graph.compile()

step1 = compiled.invoke({"x": 0.5}, context={"r": 3.0})
# {'x': [0.5, 0.75]}
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `state_schema` | `type[StateT]` | Yes | The schema class that defines the state. |
| `context_schema` | `type[ContextT] \| None` | No | The schema class that defines the runtime context.  Use this to expose immutable context data to your nodes, like `user_id`, `db_conn`, etc. (default: `None`) |
| `input_schema` | `type[InputT] \| None` | No | The schema class that defines the input to the graph. (default: `None`) |
| `output_schema` | `type[OutputT] \| None` | No | The schema class that defines the output from the graph. (default: `None`) |

## Extends

- `Generic[StateT, ContextT, InputT, OutputT]`

## Constructors

```python
__init__(
    self,
    state_schema: type[StateT],
    context_schema: type[ContextT] | None = None,
    *,
    input_schema: type[InputT] | None = None,
    output_schema: type[OutputT] | None = None,
    **kwargs: Unpack[DeprecatedKwargs] = {},
) -> None
```

| Name | Type |
|------|------|
| `state_schema` | `type[StateT]` |
| `context_schema` | `type[ContextT] \| None` |
| `input_schema` | `type[InputT] \| None` |
| `output_schema` | `type[OutputT] \| None` |


## Properties

- `edges`
- `nodes`
- `branches`
- `channels`
- `managed`
- `schemas`
- `waiting_edges`
- `compiled`
- `state_schema`
- `context_schema`
- `input_schema`
- `output_schema`

## Methods

- [`set_node_defaults()`](https://reference.langchain.com/python/langgraph/graph/state/StateGraph/set_node_defaults)
- [`add_node()`](https://reference.langchain.com/python/langgraph/graph/state/StateGraph/add_node)
- [`add_edge()`](https://reference.langchain.com/python/langgraph/graph/state/StateGraph/add_edge)
- [`add_conditional_edges()`](https://reference.langchain.com/python/langgraph/graph/state/StateGraph/add_conditional_edges)
- [`add_sequence()`](https://reference.langchain.com/python/langgraph/graph/state/StateGraph/add_sequence)
- [`set_entry_point()`](https://reference.langchain.com/python/langgraph/graph/state/StateGraph/set_entry_point)
- [`set_conditional_entry_point()`](https://reference.langchain.com/python/langgraph/graph/state/StateGraph/set_conditional_entry_point)
- [`set_finish_point()`](https://reference.langchain.com/python/langgraph/graph/state/StateGraph/set_finish_point)
- [`validate()`](https://reference.langchain.com/python/langgraph/graph/state/StateGraph/validate)
- [`compile()`](https://reference.langchain.com/python/langgraph/graph/state/StateGraph/compile)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/graph/state.py#L130)