# CronsSearch

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/auth/types/CronsSearch)

Payload for searching cron jobs.

???+ example "Examples"

    ```python
    search_params = {
        "assistant_id": UUID("123e4567-e89b-12d3-a456-426614174000"),
        "thread_id": UUID("123e4567-e89b-12d3-a456-426614174001"),
        "limit": 10,
        "offset": 0
    }
    ```

## Signature

```python
CronsSearch()
```

## Extends

- `typing.TypedDict`

## Constructors

```python
__init__(
    assistant_id: UUID | None,
    thread_id: UUID | None,
    limit: int,
    offset: int,
)
```

| Name | Type |
|------|------|
| `assistant_id` | `UUID \| None` |
| `thread_id` | `UUID \| None` |
| `limit` | `int` |
| `offset` | `int` |


## Properties

- `assistant_id`
- `thread_id`
- `limit`
- `offset`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/auth/types.py#L834)