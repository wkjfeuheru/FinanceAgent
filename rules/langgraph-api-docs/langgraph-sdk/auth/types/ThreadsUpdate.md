# ThreadsUpdate

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/auth/types/ThreadsUpdate)

Parameters for updating a thread or run.

Called for updates to a thread, thread version, or run
cancellation.

## Signature

```python
ThreadsUpdate()
```

## Extends

- `typing.TypedDict`

## Constructors

```python
__init__(
    thread_id: UUID,
    metadata: MetadataInput,
    action: typing.Literal['interrupt', 'rollback'] | None,
)
```

| Name | Type |
|------|------|
| `thread_id` | `UUID` |
| `metadata` | `MetadataInput` |
| `action` | `typing.Literal['interrupt', 'rollback'] \| None` |


## Properties

- `thread_id`
- `metadata`
- `action`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/auth/types.py#L485)