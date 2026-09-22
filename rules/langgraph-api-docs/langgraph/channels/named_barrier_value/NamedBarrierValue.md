# NamedBarrierValue

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/channels/named_barrier_value/NamedBarrierValue)

A channel that waits until all named values are received before making the value available.

## Signature

```python
NamedBarrierValue(
    self,
    typ: type[Value],
    names: set[Value],
)
```

## Extends

- `Generic[Value]`
- `BaseChannel[Value, Value, set[Value]]`

## Constructors

```python
__init__(
    self,
    typ: type[Value],
    names: set[Value],
) -> None
```

| Name | Type |
|------|------|
| `typ` | `type[Value]` |
| `names` | `set[Value]` |


## Properties

- `names`
- `seen`
- `ValueType`
- `UpdateType`

## Methods

- [`copy()`](https://reference.langchain.com/python/langgraph/channels/named_barrier_value/NamedBarrierValue/copy)
- [`checkpoint()`](https://reference.langchain.com/python/langgraph/channels/named_barrier_value/NamedBarrierValue/checkpoint)
- [`from_checkpoint()`](https://reference.langchain.com/python/langgraph/channels/named_barrier_value/NamedBarrierValue/from_checkpoint)
- [`update()`](https://reference.langchain.com/python/langgraph/channels/named_barrier_value/NamedBarrierValue/update)
- [`get()`](https://reference.langchain.com/python/langgraph/channels/named_barrier_value/NamedBarrierValue/get)
- [`is_available()`](https://reference.langchain.com/python/langgraph/channels/named_barrier_value/NamedBarrierValue/is_available)
- [`consume()`](https://reference.langchain.com/python/langgraph/channels/named_barrier_value/NamedBarrierValue/consume)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/channels/named_barrier_value.py#L13)