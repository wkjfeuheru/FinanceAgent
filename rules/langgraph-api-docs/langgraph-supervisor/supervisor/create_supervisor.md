# create_supervisor

> **Function** in `langgraph_supervisor`

📖 [View in docs](https://reference.langchain.com/python/langgraph-supervisor/supervisor/create_supervisor)

Create a multi-agent supervisor.

## Signature

```python
create_supervisor(
    agents: list[Pregel],
    *,
    model: LanguageModelLike,
    tools: list[BaseTool | Callable] | ToolNode | None = None,
    prompt: Prompt | None = None,
    response_format: Optional[Union[StructuredResponseSchema, tuple[str, StructuredResponseSchema]]] = None,
    pre_model_hook: Optional[RunnableLike] = None,
    post_model_hook: Optional[RunnableLike] = None,
    parallel_tool_calls: bool = False,
    state_schema: StateSchemaType | None = None,
    context_schema: Type[Any] | None = None,
    output_mode: OutputMode = 'last_message',
    add_handoff_messages: bool = True,
    handoff_tool_prefix: Optional[str] = None,
    add_handoff_back_messages: Optional[bool] = None,
    supervisor_name: str = 'supervisor',
    include_agent_name: AgentNameMode | None = None,
    **deprecated_kwargs: Unpack[DeprecatedKwargs] = {},
) -> StateGraph
```

## Description

**Example:**

```python
from langchain_openai import ChatOpenAI

from langgraph_supervisor import create_supervisor
from langgraph.prebuilt import create_react_agent

# Create specialized agents

def add(a: float, b: float) -> float:
    '''Add two numbers.'''
    return a + b

def web_search(query: str) -> str:
    '''Search the web for information.'''
    return 'Here are the headcounts for each of the FAANG companies in 2024...'

math_agent = create_react_agent(
    model="openai:gpt-4o",
    tools=[add],
    name="math_expert",
)

research_agent = create_react_agent(
    model="openai:gpt-4o",
    tools=[web_search],
    name="research_expert",
)

# Create supervisor workflow
workflow = create_supervisor(
    [research_agent, math_agent],
    model=ChatOpenAI(model="gpt-4o"),
)

# Compile and run
app = workflow.compile()
result = app.invoke({
    "messages": [
        {
            "role": "user",
            "content": "what's the combined headcount of the FAANG companies in 2024?"
        }
    ]
})
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `agents` | `list[Pregel]` | Yes | List of agents to manage. An agent can be a LangGraph [`CompiledStateGraph`](https://reference.langchain.com/python/langgraph/graphs/#langgraph.graph.state.CompiledStateGraph), a functional API workflow, or any other [Pregel](https://reference.langchain.com/python/langgraph/pregel/#langgraph.pregel.Pregel) object. |
| `model` | `LanguageModelLike` | Yes | Language model to use for the supervisor |
| `tools` | `list[BaseTool \| Callable] \| ToolNode \| None` | No | Tools to use for the supervisor (default: `None`) |
| `prompt` | `Prompt \| None` | No | Optional prompt to use for the supervisor. Can be one of:  - `str`: This is converted to a `SystemMessage` and added to the beginning of the list of messages in `state["messages"]`. - `SystemMessage`: this is added to the beginning of the list of messages in `state["messages"]`. - `Callable`: This function should take in full graph state and the output is then passed to the language model. - `Runnable`: This runnable should take in full graph state and the output is then passed to the language model. (default: `None`) |
| `response_format` | `Optional[Union[StructuredResponseSchema, tuple[str, StructuredResponseSchema]]]` | No | An optional schema for the final supervisor output.  If provided, output will be formatted to match the given schema and returned in the `'structured_response'` state key.  If not provided, `structured_response` will not be present in the output state.  Can be passed in as:      - An OpenAI function/tool schema,     - A JSON Schema,     - A TypedDict class,     - A Pydantic class.     - A tuple `(prompt, schema)`, where schema is one of the above.         The prompt will be used together with the model that is being used to generate the structured response.  !!! Important     `response_format` requires the model to support `.with_structured_output`  !!! Note     `response_format` requires `structured_response` key in your state schema.     You can use the prebuilt `langgraph.prebuilt.chat_agent_executor.AgentStateWithStructuredResponse`. (default: `None`) |
| `pre_model_hook` | `Optional[RunnableLike]` | No | An optional node to add before the LLM node in the supervisor agent (i.e., the node that calls the LLM). Useful for managing long message histories (e.g., message trimming, summarization, etc.). Pre-model hook must be a callable or a runnable that takes in current graph state and returns a state update in the form of     ```python     # At least one of `messages` or `llm_input_messages` MUST be provided     {         # If provided, will UPDATE the `messages` in the state         "messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), ...],         # If provided, will be used as the input to the LLM,         # and will NOT UPDATE `messages` in the state         "llm_input_messages": [...],         # Any other state keys that need to be propagated         ...     }     ```  !!! Important     At least one of `messages` or `llm_input_messages` MUST be provided and will be used as an input to the `agent` node.     The rest of the keys will be added to the graph state.  !!! Warning     If you are returning `messages` in the pre-model hook, you should OVERWRITE the `messages` key by doing the following:      ```python     {         "messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *new_messages]         ...     }     ``` (default: `None`) |
| `post_model_hook` | `Optional[RunnableLike]` | No | An optional node to add after the LLM node in the supervisor agent (i.e., the node that calls the LLM). Useful for implementing human-in-the-loop, guardrails, validation, or other post-processing. Post-model hook must be a callable or a runnable that takes in current graph state and returns a state update. (default: `None`) |
| `parallel_tool_calls` | `bool` | No | Whether to allow the supervisor LLM to call tools in parallel (only OpenAI and Anthropic). Use this to control whether the supervisor can hand off to multiple agents at once.  If `True`, will enable parallel tool calls.  If `False`, will disable parallel tool calls.  !!! Important     This is currently supported only by OpenAI and Anthropic models.     To control parallel tool calling for other providers, add explicit instructions for tool use to the system prompt. (default: `False`) |
| `state_schema` | `StateSchemaType \| None` | No | State schema to use for the supervisor graph. (default: `None`) |
| `context_schema` | `Type[Any] \| None` | No | Specifies the schema for the context object that will be passed to the workflow. (default: `None`) |
| `output_mode` | `OutputMode` | No | Mode for adding managed agents' outputs to the message history in the multi-agent workflow. Can be one of:  - `full_history`: Add the entire agent message history - `last_message`: Add only the last message (default: `'last_message'`) |
| `add_handoff_messages` | `bool` | No | Whether to add a pair of `(AIMessage, ToolMessage)` to the message history when a handoff occurs. (default: `True`) |
| `handoff_tool_prefix` | `Optional[str]` | No | Optional prefix for the handoff tools (e.g., `'delegate_to_'` or `'transfer_to_'`)  If provided, the handoff tools will be named `handoff_tool_prefix_agent_name`.  If not provided, the handoff tools will be named `transfer_to_agent_name`. (default: `None`) |
| `add_handoff_back_messages` | `Optional[bool]` | No | Whether to add a pair of `(AIMessage, ToolMessage)` to the message history when returning control to the supervisor to indicate that a handoff has occurred. (default: `None`) |
| `supervisor_name` | `str` | No | Name of the supervisor node. (default: `'supervisor'`) |
| `include_agent_name` | `AgentNameMode \| None` | No | Use to specify how to expose the agent name to the underlying supervisor LLM.  - `None`: Relies on the LLM provider using the name attribute on the AI message. Currently, only OpenAI supports this. - `'inline'`: Add the agent name directly into the content field of the AI message using XML-style tags.     Example: `"How can I help you"` -> `"<name>agent_name</name><content>How can I help you?</content>"` (default: `None`) |

---

[View source on GitHub](https://github.com/langchain-ai/langgraph-supervisor-py/blob/69c808c071e0a420255155c0ef383962b4872003/langgraph_supervisor/supervisor.py#L211)