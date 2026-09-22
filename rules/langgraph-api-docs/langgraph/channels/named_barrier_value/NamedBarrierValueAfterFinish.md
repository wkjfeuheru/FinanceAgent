# NamedBarrierValueAfterFinish

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/channels/named_barrier_value/NamedBarrierValueAfterFinish)

A channel that waits until all named values are received before making the value ready to be made available. It is only made available after finish() is called.

## Signature

```python
NamedBarrierValueAfterFinish(
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
- `finished`
- `ValueType`
- `UpdateType`

## Methods

- [`copy()`](https://reference.langchain.com/python/langgraph/channels/named_barrier_value/NamedBarrierValueAfterFinish/copy)
- [`checkpoint()`](https://reference.langchain.com/python/langgraph/channels/named_barrier_value/NamedBarrierValueAfterFinish/checkpoint)
- [`from_checkpoint()`](https://reference.langchain.com/python/langgraph/channels/named_barrier_value/NamedBarrierValueAfterFinish/from_checkpoint)
- [`update()`](https://reference.langchain.com/python/langgraph/channels/named_barrier_value/NamedBarrierValueAfterFinish/update)
- [`get()`](https://reference.langchain.com/python/langgraph/channels/named_barrier_value/NamedBarrierValueAfterFinish/get)
- [`is_available()`](https://reference.langchain.com/python/langgraph/channels/named_barrier_value/NamedBarrierValueAfterFinish/is_available)
- [`consume()`](https://reference.langchain.com/python/langgraph/channels/named_barrier_value/NamedBarrierValueAfterFinish/consume)
- [`finish()`](https://reference.langchain.com/python/langgraph/channels/named_barrier_value/NamedBarrierValueAfterFinish/finish)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/channels/named_barrier_value.py#L84)