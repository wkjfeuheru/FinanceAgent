# PregelRunner

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/pregel/_runner/PregelRunner)

Responsible for executing a set of Pregel tasks concurrently, committing
their writes, yielding control to caller when there is output to emit, and
interrupting other tasks if appropriate.

## Signature

```python
PregelRunner(
    self,
    *,
    submit: weakref.ref[Submit],
    put_writes: weakref.ref[Callable[[str, Sequence[tuple[str, Any]]], None]],
    use_astream: bool = False,
    node_finished: Callable[[str], None] | None = None,
    node_error_handler_map: Mapping[str, str] | None = None,
    schedule_error_handler: Callable[[PregelExecutableTask, BaseException], PregelExecutableTask | None] | None = None,
    aschedule_error_handler: Callable[[PregelExecutableTask, BaseException], Awaitable[PregelExecutableTask | None]] | None = None,
)
```

## Constructors

```python
__init__(
    self,
    *,
    submit: weakref.ref[Submit],
    put_writes: weakref.ref[Callable[[str, Sequence[tuple[str, Any]]], None]],
    use_astream: bool = False,
    node_finished: Callable[[str], None] | None = None,
    node_error_handler_map: Mapping[str, str] | None = None,
    schedule_error_handler: Callable[[PregelExecutableTask, BaseException], PregelExecutableTask | None] | None = None,
    aschedule_error_handler: Callable[[PregelExecutableTask, BaseException], Awaitable[PregelExecutableTask | None]] | None = None,
) -> None
```

| Name | Type |
|------|------|
| `submit` | `weakref.ref[Submit]` |
| `put_writes` | `weakref.ref[Callable[[str, Sequence[tuple[str, Any]]], None]]` |
| `use_astream` | `bool` |
| `node_finished` | `Callable[[str], None] \| None` |
| `node_error_handler_map` | `Mapping[str, str] \| None` |
| `schedule_error_handler` | `Callable[[PregelExecutableTask, BaseException], PregelExecutableTask \| None] \| None` |
| `aschedule_error_handler` | `Callable[[PregelExecutableTask, BaseException], Awaitable[PregelExecutableTask \| None]] \| None` |


## Properties

- `submit`
- `put_writes`
- `use_astream`
- `node_finished`
- `node_error_handler_map`
- `error_handler_nodes`
- `schedule_error_handler`
- `aschedule_error_handler`

## Methods

- [`tick()`](https://reference.langchain.com/python/langgraph/pregel/_runner/PregelRunner/tick)
- [`atick()`](https://reference.langchain.com/python/langgraph/pregel/_runner/PregelRunner/atick)
- [`commit()`](https://reference.langchain.com/python/langgraph/pregel/_runner/PregelRunner/commit)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/pregel/_runner.py#L135)