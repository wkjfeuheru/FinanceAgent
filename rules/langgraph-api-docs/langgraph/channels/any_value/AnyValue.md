# AnyValue

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/channels/any_value/AnyValue)

Stores the last value received, assumes that if multiple values are
received, they are all equal.

## Signature

```python
AnyValue(
    self,
    typ: Any,
    key: str = '',
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
    key: str = '',
) -> None
```

| Name | Type |
|------|------|
| `typ` | `Any` |
| `key` | `str` |


## Properties

- `value`
- `ValueType`
- `UpdateType`

## Methods

- [`copy()`](https://reference.langchain.com/python/langgraph/channels/any_value/AnyValue/copy)
- [`from_checkpoint()`](https://reference.langchain.com/python/langgraph/channels/any_value/AnyValue/from_checkpoint)
- [`update()`](https://reference.langchain.com/python/langgraph/channels/any_value/AnyValue/update)
- [`get()`](https://reference.langchain.com/python/langgraph/channels/any_value/AnyValue/get)
- [`is_available()`](https://reference.langchain.com/python/langgraph/channels/any_value/AnyValue/is_available)
- [`checkpoint()`](https://reference.langchain.com/python/langgraph/channels/any_value/AnyValue/checkpoint)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/channels/any_value.py#L15)