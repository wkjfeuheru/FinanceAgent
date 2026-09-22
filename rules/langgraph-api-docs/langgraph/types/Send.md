# Send

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/types/Send)

A message or packet to send to a specific node in the graph.

The `Send` class is used within a `StateGraph`'s conditional edges to
dynamically invoke a node with a custom state at the next step.

Importantly, the sent state can differ from the core graph's state,
allowing for flexible and dynamic workflow management.

One such example is a "map-reduce" workflow where your graph invokes
the same node multiple times in parallel with different states,
before aggregating the results back into the main graph's state.

## Signature

```python
Send(
    self,
    /,
    node: str,
    arg: Any,
    *,
    timeout: float | timedelta | TimeoutPolicy | None = None,
)
```

## Description

!!! example

```python
from typing import Annotated
from langgraph.types import Send
from langgraph.graph import END, START
from langgraph.graph import StateGraph
import operator

class OverallState(TypedDict):
    subjects: list[str]
    jokes: Annotated[list[str], operator.add]

def continue_to_jokes(state: OverallState):
    return [Send("generate_joke", {"subject": s}) for s in state["subjects"]]

builder = StateGraph(OverallState)
builder.add_node("generate_joke", lambda state: {"jokes": [f"Joke about {state['subject']}"]})
builder.add_conditional_edges(START, continue_to_jokes)
builder.add_edge("generate_joke", END)
graph = builder.compile()

# Invoking with two subjects results in a generated joke for each
graph.invoke({"subjects": ["cats", "dogs"]})
# {'subjects': ['cats', 'dogs'], 'jokes': ['Joke about cats', 'Joke about dogs']}
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `node` | `str` | Yes | The name of the target node to send the message to. |
| `arg` | `Any` | Yes | The state or message to send to the target node. |
| `timeout` | `float \| timedelta \| TimeoutPolicy \| None` | No | Optional timeout policy for this specific pushed task. A number or `timedelta` is treated as a hard `run_timeout`. (default: `None`) |

## Constructors

```python
__init__(
    self,
    /,
    node: str,
    arg: Any,
    *,
    timeout: float | timedelta | TimeoutPolicy | None = None,
) -> None
```

| Name | Type |
|------|------|
| `node` | `str` |
| `arg` | `Any` |
| `timeout` | `float \| timedelta \| TimeoutPolicy \| None` |


## Properties

- `node`
- `arg`
- `timeout`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/types.py#L664)