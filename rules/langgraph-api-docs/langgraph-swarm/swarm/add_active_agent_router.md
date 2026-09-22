# add_active_agent_router

> **Function** in `langgraph_swarm`

📖 [View in docs](https://reference.langchain.com/python/langgraph-swarm/swarm/add_active_agent_router)

Add a router to the currently active agent to the StateGraph.

## Signature

```python
add_active_agent_router(
    builder: StateGraph,
    *,
    route_to: list[str],
    default_active_agent: str,
) -> StateGraph
```

## Description

**Example:**

```python
from langchain.checkpoint.memory import InMemorySaver
from langchain.agents import create_agent
from langgraph.graph import StateGraph
from langgraph_swarm import SwarmState, create_handoff_tool, add_active_agent_router

def add(a: int, b: int) -> int:
    '''Add two numbers'''
    return a + b

alice = create_agent(
    "openai:gpt-4o",
    tools=[
        add,
        create_handoff_tool(
            agent_name="Bob",
            description="Transfer to Bob",
        ),
    ],
    system_prompt="You are Alice, an addition expert.",
    name="Alice",
)

bob = create_agent(
    "openai:gpt-4o",
    tools=[
        create_handoff_tool(
            agent_name="Alice",
            description="Transfer to Alice, she can help with math",
        ),
    ],
    system_prompt="You are Bob, you speak like a pirate.",
    name="Bob",
)

checkpointer = InMemorySaver()
workflow = (
    StateGraph(SwarmState)
    .add_node(alice, destinations=("Bob",))
    .add_node(bob, destinations=("Alice",))
)
# this is the router that enables us to keep track of the last active agent
workflow = add_active_agent_router(
    builder=workflow,
    route_to=["Alice", "Bob"],
    default_active_agent="Alice",
)

# compile the workflow
app = workflow.compile(checkpointer=checkpointer)

config = {"configurable": {"thread_id": "1"}}
turn_1 = app.invoke(
    {"messages": [{"role": "user", "content": "i'd like to speak to Bob"}]},
    config,
)
turn_2 = app.invoke(
    {"messages": [{"role": "user", "content": "what's 5 + 7?"}]},
    config,
)
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `builder` | `StateGraph` | Yes | The graph builder (StateGraph) to add the router to. |
| `route_to` | `list[str]` | Yes | A list of agent (node) names to route to. |
| `default_active_agent` | `str` | Yes | Name of the agent to route to by default (if no agents are currently active). |

## Returns

`StateGraph`

StateGraph with the router added.

---

[View source on GitHub](https://github.com/langchain-ai/langgraph-swarm-py/blob/366f9c54f1bc978603e478d2612e57e65e0b0859/langgraph_swarm/swarm.py#L72)