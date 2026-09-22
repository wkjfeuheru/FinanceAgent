# ExecutionInfo

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/runtime/ExecutionInfo)

Read-only execution info/metadata for the execution of current thread/run/node.

## Signature

```python
ExecutionInfo(
    self,
    checkpoint_id: str,
    checkpoint_ns: str,
    task_id: str,
    thread_id: str | None = None,
    run_id: str | None = None,
    node_attempt: int = 1,
    node_first_attempt_time: float | None = None,
)
```

## Constructors

```python
__init__(
    self,
    checkpoint_id: str,
    checkpoint_ns: str,
    task_id: str,
    thread_id: str | None = None,
    run_id: str | None = None,
    node_attempt: int = 1,
    node_first_attempt_time: float | None = None,
) -> None
```

| Name | Type |
|------|------|
| `checkpoint_id` | `str` |
| `checkpoint_ns` | `str` |
| `task_id` | `str` |
| `thread_id` | `str \| None` |
| `run_id` | `str \| None` |
| `node_attempt` | `int` |
| `node_first_attempt_time` | `float \| None` |


## Properties

- `checkpoint_id`
- `checkpoint_ns`
- `task_id`
- `thread_id`
- `run_id`
- `node_attempt`
- `node_first_attempt_time`

## Methods

- [`patch()`](https://reference.langchain.com/python/langgraph/runtime/ExecutionInfo/patch)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/runtime.py#L26)