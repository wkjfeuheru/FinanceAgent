# CustomStreamPart

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/types/CustomStreamPart)

Stream part emitted for `stream_mode="custom"`.

`data` is whatever value was passed to `StreamWriter` inside a node.

## Signature

```python
CustomStreamPart()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    type: Literal['custom'],
    ns: tuple[str, ...],
    data: Any,
)
```

| Name | Type |
|------|------|
| `type` | `Literal['custom']` |
| `ns` | `tuple[str, ...]` |
| `data` | `Any` |


## Properties

- `type`
- `ns`
- `data`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/types.py#L299)