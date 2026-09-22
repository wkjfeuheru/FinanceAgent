# PregelScratchpad

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/_internal/_scratchpad/PregelScratchpad)

## Signature

```python
PregelScratchpad(
    self,
    step: int,
    stop: int,
    call_counter: Callable[[], int],
    interrupt_counter: Callable[[], int],
    get_null_resume: Callable[[bool], Any],
    resume: list[Any],
    subgraph_counter: Callable[[], int],
)
```

## Constructors

```python
__init__(
    self,
    step: int,
    stop: int,
    call_counter: Callable[[], int],
    interrupt_counter: Callable[[], int],
    get_null_resume: Callable[[bool], Any],
    resume: list[Any],
    subgraph_counter: Callable[[], int],
) -> None
```

| Name | Type |
|------|------|
| `step` | `int` |
| `stop` | `int` |
| `call_counter` | `Callable[[], int]` |
| `interrupt_counter` | `Callable[[], int]` |
| `get_null_resume` | `Callable[[bool], Any]` |
| `resume` | `list[Any]` |
| `subgraph_counter` | `Callable[[], int]` |


## Properties

- `step`
- `stop`
- `call_counter`
- `interrupt_counter`
- `get_null_resume`
- `resume`
- `subgraph_counter`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/_internal/_scratchpad.py#L8)