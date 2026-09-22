# add_messages

> **Function** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/graph/message/add_messages)

Merges two lists of messages, updating existing messages by ID.

By default, this ensures the state is "append-only", unless the
new message has the same ID as an existing message.

## Signature

```python
add_messages(
    left: Messages,
    right: Messages,
    *,
    format: Literal['langchain-openai'] | None = None,
) -> Messages
```

## Description

**Basic usage:**

```python
from langchain_core.messages import AIMessage, HumanMessage

msgs1 = [HumanMessage(content="Hello", id="1")]
msgs2 = [AIMessage(content="Hi there!", id="2")]
add_messages(msgs1, msgs2)
# [HumanMessage(content='Hello', id='1'), AIMessage(content='Hi there!', id='2')]
```

**Overwrite existing message:**

```python
msgs1 = [HumanMessage(content="Hello", id="1")]
msgs2 = [HumanMessage(content="Hello again", id="1")]
add_messages(msgs1, msgs2)
# [HumanMessage(content='Hello again', id='1')]
```

**Use in a StateGraph:**

```python
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph

class State(TypedDict):
    messages: Annotated[list, add_messages]

builder = StateGraph(State)
builder.add_node("chatbot", lambda state: {"messages": [("assistant", "Hello")]})
builder.set_entry_point("chatbot")
builder.set_finish_point("chatbot")
graph = builder.compile()
graph.invoke({})
# {'messages': [AIMessage(content='Hello', id=...)]}
```

**Use OpenAI message format:**

```python
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, add_messages

class State(TypedDict):
    messages: Annotated[list, add_messages(format="langchain-openai")]

def chatbot_node(state: State) -> list:
    return {
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Here's an image:",
                        "cache_control": {"type": "ephemeral"},
                    },
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": "1234",
                        },
                    },
                ],
            },
        ]
    }

builder = StateGraph(State)
builder.add_node("chatbot", chatbot_node)
builder.set_entry_point("chatbot")
builder.set_finish_point("chatbot")
graph = builder.compile()
graph.invoke({"messages": []})
# {
#     'messages': [
#         HumanMessage(
#             content=[
#                 {"type": "text", "text": "Here's an image:"},
#                 {
#                     "type": "image_url",
#                     "image_url": {"url": "data:image/jpeg;base64,1234"},
#                 },
#             ],
#         ),
#     ]
# }
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `left` | `Messages` | Yes | The base list of `Messages`. |
| `right` | `Messages` | Yes | The list of `Messages` (or single `Message`) to merge into the base list. |
| `format` | `Literal['langchain-openai'] \| None` | No | The format to return messages in. If `None` then `Messages` will be returned as is. If `langchain-openai` then `Messages` will be returned as `BaseMessage` objects with their contents formatted to match OpenAI message format, meaning contents can be string, `'text'` blocks, or `'image_url'` blocks and tool responses are returned as their own `ToolMessage` objects.  !!! important "Requirement"      Must have `langchain-core>=0.3.11` installed to use this feature. (default: `None`) |

## Returns

`Messages`

A new list of messages with the messages from `right` merged into `left`.

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/graph/message.py#L60)