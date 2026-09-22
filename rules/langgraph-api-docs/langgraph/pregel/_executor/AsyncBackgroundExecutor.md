# AsyncBackgroundExecutor

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/pregel/_executor/AsyncBackgroundExecutor)

A context manager that runs async tasks in the background.
Uses the current event loop to delegate tasks to asyncio tasks.
On exit,
- cancels any tasks with `__cancel_on_exit__=True`
- waits for all tasks to finish
- re-raises the first exception from tasks with `__reraise_on_exit__=True`
  ignoring CancelledError

## Signature

```python
AsyncBackgroundExecutor(
    self,
    config: RunnableConfig,
)
```

## Extends

- `AbstractAsyncContextManager`

## Constructors

```python
__init__(
    self,
    config: RunnableConfig,
) -> None
```

| Name | Type |
|------|------|
| `config` | `RunnableConfig` |


## Properties

- `tasks`
- `sentinel`
- `loop`
- `semaphore`

## Methods

- [`submit()`](https://reference.langchain.com/python/langgraph/pregel/_executor/AsyncBackgroundExecutor/submit)
- [`done()`](https://reference.langchain.com/python/langgraph/pregel/_executor/AsyncBackgroundExecutor/done)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/pregel/_executor.py#L122)