# create_swarm

> **Function** in `langgraph_swarm`

📖 [View in docs](https://reference.langchain.com/python/langgraph-swarm/swarm/create_swarm)

Create a multi-agent swarm.

## Signature

```python
create_swarm(
    agents: list[Pregel],
    *,
    default_active_agent: str,
    state_schema: StateSchemaType = SwarmState,
    context_schema: type[Any] | None = None,
    **deprecated_kwargs: Unpack[DeprecatedKwargs] = {},
) -> StateGraph
```

## Description

**Example:**

```python
from langgraph.checkpoint.memory import InMemorySaver
from langchain.agents import create_agent
from langgraph_swarm import create_handoff_tool, create_swarm

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
workflow = create_swarm(
    [alice, bob],
    default_active_agent="Alice"
)
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
| `agents` | `list[Pregel]` | Yes | List of agents to add to the swarm An agent can be a LangGraph [CompiledStateGraph](https://langchain-ai.github.io/langgraph/reference/graphs/#langgraph.graph.state.CompiledStateGraph), a functional API [workflow](https://langchain-ai.github.io/langgraph/reference/func/#langgraph.func.entrypoint), or any other [Pregel](https://langchain-ai.github.io/langgraph/reference/pregel/#langgraph.pregel.Pregel) object. |
| `default_active_agent` | `str` | Yes | Name of the agent to route to by default (if no agents are currently active). |
| `state_schema` | `StateSchemaType` | No | State schema to use for the multi-agent graph. (default: `SwarmState`) |
| `context_schema` | `type[Any] \| None` | No | Specifies the schema for the context object that will be passed to the workflow. (default: `None`) |

## Returns

`StateGraph`

A multi-agent swarm StateGraph.

---

[View source on GitHub](https://github.com/langchain-ai/langgraph-swarm-py/blob/366f9c54f1bc978603e478d2612e57e65e0b0859/langgraph_swarm/swarm.py#L170)