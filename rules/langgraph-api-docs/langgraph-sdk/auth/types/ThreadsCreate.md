# ThreadsCreate

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/auth/types/ThreadsCreate)

Parameters for creating a new thread.

???+ example "Examples"

    ```python
    create_params = {
        "thread_id": UUID("123e4567-e89b-12d3-a456-426614174000"),
        "metadata": {"owner": "user123"},
        "if_exists": "do_nothing"
    }
    ```

## Signature

```python
ThreadsCreate()
```

## Extends

- `typing.TypedDict`

## Constructors

```python
__init__(
    thread_id: UUID,
    metadata: MetadataInput,
    if_exists: OnConflictBehavior,
    ttl: ThreadTTL,
)
```

| Name | Type |
|------|------|
| `thread_id` | `UUID` |
| `metadata` | `MetadataInput` |
| `if_exists` | `OnConflictBehavior` |
| `ttl` | `ThreadTTL` |


## Properties

- `thread_id`
- `metadata`
- `if_exists`
- `ttl`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/auth/types.py#L443)