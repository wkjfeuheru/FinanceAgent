# ThreadsSearch

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/auth/types/ThreadsSearch)

Parameters for searching threads.

Called for searches to threads or runs.

## Signature

```python
ThreadsSearch()
```

## Extends

- `typing.TypedDict`

## Constructors

```python
__init__(
    metadata: MetadataInput,
    values: MetadataInput,
    status: ThreadStatus | None,
    limit: int,
    offset: int,
    ids: Sequence[UUID] | None,
    thread_id: UUID | None,
)
```

| Name | Type |
|------|------|
| `metadata` | `MetadataInput` |
| `values` | `MetadataInput` |
| `status` | `ThreadStatus \| None` |
| `limit` | `int` |
| `offset` | `int` |
| `ids` | `Sequence[UUID] \| None` |
| `thread_id` | `UUID \| None` |


## Properties

- `metadata`
- `values`
- `status`
- `limit`
- `offset`
- `ids`
- `thread_id`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/auth/types.py#L515)