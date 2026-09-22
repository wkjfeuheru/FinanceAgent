# BaseChannel

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/channels/base/BaseChannel)

Base class for all channels.

## Signature

```python
BaseChannel(
    self,
    typ: Any,
    key: str = '',
)
```

## Extends

- `Generic[Value, Update, Checkpoint]`
- `ABC`

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

- `typ`
- `key`
- `ValueType`
- `UpdateType`

## Methods

- [`copy()`](https://reference.langchain.com/python/langgraph/channels/base/BaseChannel/copy)
- [`checkpoint()`](https://reference.langchain.com/python/langgraph/channels/base/BaseChannel/checkpoint)
- [`from_checkpoint()`](https://reference.langchain.com/python/langgraph/channels/base/BaseChannel/from_checkpoint)
- [`get()`](https://reference.langchain.com/python/langgraph/channels/base/BaseChannel/get)
- [`is_available()`](https://reference.langchain.com/python/langgraph/channels/base/BaseChannel/is_available)
- [`update()`](https://reference.langchain.com/python/langgraph/channels/base/BaseChannel/update)
- [`consume()`](https://reference.langchain.com/python/langgraph/channels/base/BaseChannel/consume)
- [`finish()`](https://reference.langchain.com/python/langgraph/channels/base/BaseChannel/finish)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/channels/base.py#L19)