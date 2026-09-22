# CronsCreate

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/auth/types/CronsCreate)

Payload for creating a cron job.

???+ example "Examples"

    ```python
    create_params = {
        "payload": {"key": "value"},
        "schedule": "0 0 * * *",
        "cron_id": UUID("123e4567-e89b-12d3-a456-426614174000"),
        "thread_id": UUID("123e4567-e89b-12d3-a456-426614174001"),
        "user_id": "user123",
        "end_time": datetime(2024, 3, 16, 10, 0, 0)
    }
    ```

## Signature

```python
CronsCreate()
```

## Extends

- `typing.TypedDict`

## Constructors

```python
__init__(
    payload: dict[str, typing.Any],
    schedule: str,
    cron_id: UUID | None,
    thread_id: UUID | None,
    user_id: str | None,
    end_time: datetime | None,
)
```

| Name | Type |
|------|------|
| `payload` | `dict[str, typing.Any]` |
| `schedule` | `str` |
| `cron_id` | `UUID \| None` |
| `thread_id` | `UUID \| None` |
| `user_id` | `str \| None` |
| `end_time` | `datetime \| None` |


## Properties

- `payload`
- `schedule`
- `cron_id`
- `thread_id`
- `user_id`
- `end_time`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/auth/types.py#L742)