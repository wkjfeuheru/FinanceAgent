# ThreadsDelete

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/auth/types/ThreadsDelete)

Parameters for deleting a thread.

Called for deletes to a thread, thread version, or run

## Signature

```python
ThreadsDelete()
```

## Extends

- `typing.TypedDict`

## Constructors

```python
__init__(
    thread_id: UUID,
    run_id: UUID | None,
)
```

| Name | Type |
|------|------|
| `thread_id` | `UUID` |
| `run_id` | `UUID \| None` |


## Properties

- `thread_id`
- `run_id`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/auth/types.py#L502)