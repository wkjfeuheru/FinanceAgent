# UntrackedValue

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/channels/untracked_value/UntrackedValue)

Stores the last value received, never checkpointed.

## Signature

```python
UntrackedValue(
    self,
    typ: type[Value],
    guard: bool = True,
)
```

## Extends

- `Generic[Value]`
- `BaseChannel[Value, Value, Value]`

## Constructors

```python
__init__(
    self,
    typ: type[Value],
    guard: bool = True,
) -> None
```

| Name | Type |
|------|------|
| `typ` | `type[Value]` |
| `guard` | `bool` |


## Properties

- `guard`
- `value`
- `ValueType`
- `UpdateType`

## Methods

- [`copy()`](https://reference.langchain.com/python/langgraph/channels/untracked_value/UntrackedValue/copy)
- [`checkpoint()`](https://reference.langchain.com/python/langgraph/channels/untracked_value/UntrackedValue/checkpoint)
- [`from_checkpoint()`](https://reference.langchain.com/python/langgraph/channels/untracked_value/UntrackedValue/from_checkpoint)
- [`update()`](https://reference.langchain.com/python/langgraph/channels/untracked_value/UntrackedValue/update)
- [`get()`](https://reference.langchain.com/python/langgraph/channels/untracked_value/UntrackedValue/get)
- [`is_available()`](https://reference.langchain.com/python/langgraph/channels/untracked_value/UntrackedValue/is_available)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/channels/untracked_value.py#L15)