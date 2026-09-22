# FuturesDict

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/pregel/_runner/FuturesDict)

## Signature

```python
FuturesDict(
    self,
    event: E,
    callback: weakref.ref[Callable[[PregelExecutableTask, BaseException | None], None]],
    should_stop: Callable[[set[F]], bool],
    future_type: type[F],
)
```

## Extends

- `Generic[F, E]`
- `dict[F, PregelExecutableTask | None]`

## Constructors

```python
__init__(
    self,
    event: E,
    callback: weakref.ref[Callable[[PregelExecutableTask, BaseException | None], None]],
    should_stop: Callable[[set[F]], bool],
    future_type: type[F],
) -> None
```

| Name | Type |
|------|------|
| `event` | `E` |
| `callback` | `weakref.ref[Callable[[PregelExecutableTask, BaseException \| None], None]]` |
| `should_stop` | `Callable[[set[F]], bool]` |
| `future_type` | `type[F]` |


## Properties

- `event`
- `callback`
- `should_stop`
- `counter`
- `done`
- `lock`

## Methods

- [`on_done()`](https://reference.langchain.com/python/langgraph/pregel/_runner/FuturesDict/on_done)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/pregel/_runner.py#L75)