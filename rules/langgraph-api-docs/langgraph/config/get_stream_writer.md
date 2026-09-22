# get_stream_writer

> **Function** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/config/get_stream_writer)

Access LangGraph [`StreamWriter`][langgraph.types.StreamWriter] from inside a graph node or entrypoint task at runtime.

Can be called from inside any [`StateGraph`][langgraph.graph.StateGraph] node or
functional API [`task`][langgraph.func.task].

!!! warning "Async with Python < 3.11"

    If you are using Python < 3.11 and are running LangGraph asynchronously,
    `get_stream_writer()` won't work since it uses [`contextvar`](https://docs.python.org/3/library/contextvars.html) propagation (only available in [Python >= 3.11](https://docs.python.org/3/library/asyncio-task.html#asyncio.create_task)).

## Signature

```python
get_stream_writer() -> StreamWriter
```

## Description

**Using with `StateGraph`:**

```python
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START
from langgraph.config import get_stream_writer

class State(TypedDict):
    foo: int

def my_node(state: State):
    my_stream_writer = get_stream_writer()
    my_stream_writer({"custom_data": "Hello!"})
    return {"foo": state["foo"] + 1}

graph = (
    StateGraph(State)
    .add_node(my_node)
    .add_edge(START, "my_node")
    .compile(store=store)
)

for chunk in graph.stream({"foo": 1}, stream_mode="custom"):
    print(chunk)
```

```pycon
{"custom_data": "Hello!"}
```

**Using with functional API:**

```python
from langgraph.func import entrypoint, task
from langgraph.config import get_stream_writer

@task
def my_task(value: int):
    my_stream_writer = get_stream_writer()
    my_stream_writer({"custom_data": "Hello!"})
    return value + 1

@entrypoint(store=store)
def workflow(value: int):
    return my_task(value).result()

for chunk in workflow.stream(1, stream_mode="custom"):
    print(chunk)
```

```pycon
{"custom_data": "Hello!"}
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/config.py#L126)