# final

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/func/entrypoint/final)

A primitive that can be returned from an entrypoint.

This primitive allows to save a value to the checkpointer distinct from the
return value from the entrypoint.

## Signature

```python
final(
    self,
    *,
    value: R,
    save: S,
)
```

## Description

**Decoupling the return value and the save value:**

```python
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.func import entrypoint

@entrypoint(checkpointer=InMemorySaver())
def my_workflow(
    number: int,
    *,
    previous: Any = None,
) -> entrypoint.final[int, int]:
    previous = previous or 0
    # This will return the previous value to the caller, saving
    # 2 * number to the checkpoint, which will be used in the next invocation
    # for the `previous` parameter.
    return entrypoint.final(value=previous, save=2 * number)

config = {"configurable": {"thread_id": "1"}}

my_workflow.invoke(3, config)  # 0 (previous was None)
my_workflow.invoke(1, config)  # 6 (previous was 3 * 2 from the previous invocation)
```

## Extends

- `Generic[R, S]`

## Constructors

```python
__init__(
    self,
    *,
    value: R,
    save: S,
) -> None
```

| Name | Type |
|------|------|
| `value` | `R` |
| `save` | `S` |


## Properties

- `value`
- `save`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/func/__init__.py#L475)