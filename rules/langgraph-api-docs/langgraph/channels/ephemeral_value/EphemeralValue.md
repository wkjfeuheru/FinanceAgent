# EphemeralValue

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/channels/ephemeral_value/EphemeralValue)

Stores the value received in the step immediately preceding, clears after.

## Signature

```python
EphemeralValue(
    self,
    typ: Any,
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
    typ: Any,
    guard: bool = True,
) -> None
```

| Name | Type |
|------|------|
| `typ` | `Any` |
| `guard` | `bool` |


## Properties

- `value`
- `guard`
- `ValueType`
- `UpdateType`

## Methods

- [`copy()`](https://reference.langchain.com/python/langgraph/channels/ephemeral_value/EphemeralValue/copy)
- [`from_checkpoint()`](https://reference.langchain.com/python/langgraph/channels/ephemeral_value/EphemeralValue/from_checkpoint)
- [`update()`](https://reference.langchain.com/python/langgraph/channels/ephemeral_value/EphemeralValue/update)
- [`get()`](https://reference.langchain.com/python/langgraph/channels/ephemeral_value/EphemeralValue/get)
- [`is_available()`](https://reference.langchain.com/python/langgraph/channels/ephemeral_value/EphemeralValue/is_available)
- [`checkpoint()`](https://reference.langchain.com/python/langgraph/channels/ephemeral_value/EphemeralValue/checkpoint)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/channels/ephemeral_value.py#L15)