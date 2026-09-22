# Runtime

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/runtime/Runtime)

Convenience class that bundles run-scoped context and other runtime utilities.

This class is injected into graph nodes and middleware. It provides access to
`context`, `store`, `stream_writer`, `previous`, and `execution_info`.

!!! note "Accessing `config`"

    `Runtime` does not include `config`. To access `RunnableConfig`, you can inject
    it directly by adding a `config: RunnableConfig` parameter to your node function
    (recommended), or use `get_config()` from `langgraph.config`.

!!! note
    `ToolRuntime` (from `langgraph.prebuilt`) is a subclass that provides similar
    functionality but is designed specifically for tools. It shares `context`, `store`,
    and `stream_writer` with `Runtime`, and adds tool-specific attributes like `config`,
    `state`, and `tool_call_id`.

!!! version-added "Added in version v0.6.0"

Example:

```python
from typing import TypedDict
from langgraph.graph import StateGraph
from dataclasses import dataclass
from langgraph.runtime import Runtime
from langgraph.store.memory import InMemoryStore

@dataclass
class Context:  # (1)!
    user_id: str

class State(TypedDict, total=False):
    response: str

store = InMemoryStore()  # (2)!
store.put(("users",), "user_123", {"name": "Alice"})

def personalized_greeting(state: State, runtime: Runtime[Context]) -> State:
    '''Generate personalized greeting using runtime context and store.'''
    user_id = runtime.context.user_id  # (3)!
    name = "unknown_user"
    if runtime.store:
        if memory := runtime.store.get(("users",), user_id):
            name = memory.value["name"]

    response = f"Hello {name}! Nice to see you again."
    return {"response": response}

graph = (
    StateGraph(state_schema=State, context_schema=Context)
    .add_node("personalized_greeting", personalized_greeting)
    .set_entry_point("personalized_greeting")
    .set_finish_point("personalized_greeting")
    .compile(store=store)
)

result = graph.invoke({}, context=Context(user_id="user_123"))
print(result)
# > {'response': 'Hello Alice! Nice to see you again.'}
```

1. Define a schema for the runtime context.
2. Create a store to persist memories and other information.
3. Use the runtime context to access the `user_id`.

## Signature

```python
Runtime(
    self,
    *,
    context: ContextT = None,
    store: BaseStore | None = None,
    stream_writer: StreamWriter = _no_op_stream_writer,
    heartbeat: Callable[[], None] = _no_op_heartbeat,
    previous: Any = None,
    execution_info: ExecutionInfo | None = None,
    server_info: ServerInfo | None = None,
    control: RunControl | None = None,
)
```

## Extends

- `Generic[ContextT]`

## Constructors

```python
__init__(
    self,
    *,
    context: ContextT = None,
    store: BaseStore | None = None,
    stream_writer: StreamWriter = _no_op_stream_writer,
    heartbeat: Callable[[], None] = _no_op_heartbeat,
    previous: Any = None,
    execution_info: ExecutionInfo | None = None,
    server_info: ServerInfo | None = None,
    control: RunControl | None = None,
) -> None
```

| Name | Type |
|------|------|
| `context` | `ContextT` |
| `store` | `BaseStore \| None` |
| `stream_writer` | `StreamWriter` |
| `heartbeat` | `Callable[[], None]` |
| `previous` | `Any` |
| `execution_info` | `ExecutionInfo \| None` |
| `server_info` | `ServerInfo \| None` |
| `control` | `RunControl \| None` |


## Properties

- `context`
- `store`
- `stream_writer`
- `heartbeat`
- `previous`
- `execution_info`
- `server_info`
- `control`
- `drain_requested`
- `drain_reason`

## Methods

- [`merge()`](https://reference.langchain.com/python/langgraph/runtime/Runtime/merge)
- [`override()`](https://reference.langchain.com/python/langgraph/runtime/Runtime/override)
- [`patch_execution_info()`](https://reference.langchain.com/python/langgraph/runtime/Runtime/patch_execution_info)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/runtime.py#L124)