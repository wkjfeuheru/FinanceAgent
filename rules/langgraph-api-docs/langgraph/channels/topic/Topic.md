# Topic

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/channels/topic/Topic)

A configurable PubSub Topic.

## Signature

```python
Topic(
    self,
    typ: type[Value],
    accumulate: bool = False,
)
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `typ` | `type[Value]` | Yes | The type of the value stored in the channel. |
| `accumulate` | `bool` | No | Whether to accumulate values across steps. If `False`, the channel will be emptied after each step. (default: `False`) |

## Extends

- `Generic[Value]`
- `BaseChannel[Sequence[Value], Value | list[Value], list[Value]]`

## Constructors

```python
__init__(
    self,
    typ: type[Value],
    accumulate: bool = False,
) -> None
```

| Name | Type |
|------|------|
| `typ` | `type[Value]` |
| `accumulate` | `bool` |


## Properties

- `accumulate`
- `values`
- `ValueType`
- `UpdateType`

## Methods

- [`copy()`](https://reference.langchain.com/python/langgraph/channels/topic/Topic/copy)
- [`checkpoint()`](https://reference.langchain.com/python/langgraph/channels/topic/Topic/checkpoint)
- [`from_checkpoint()`](https://reference.langchain.com/python/langgraph/channels/topic/Topic/from_checkpoint)
- [`update()`](https://reference.langchain.com/python/langgraph/channels/topic/Topic/update)
- [`get()`](https://reference.langchain.com/python/langgraph/channels/topic/Topic/get)
- [`is_available()`](https://reference.langchain.com/python/langgraph/channels/topic/Topic/is_available)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/channels/topic.py#L23)