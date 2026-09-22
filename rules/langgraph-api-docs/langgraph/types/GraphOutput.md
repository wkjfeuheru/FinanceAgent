# GraphOutput

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/types/GraphOutput)

Typed container returned by `invoke()` / `ainvoke()` with `version="v2"`.

## Signature

```python
GraphOutput(
    self,
    value: OutputT,
    interrupts: tuple[Interrupt, ...] = (),
)
```

## Extends

- `Generic[OutputT]`

## Constructors

```python
__init__(
    self,
    value: OutputT,
    interrupts: tuple[Interrupt, ...] = (),
) -> None
```

| Name | Type |
|------|------|
| `value` | `OutputT` |
| `interrupts` | `tuple[Interrupt, ...]` |


## Properties

- `value`
- `interrupts`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/types.py#L368)