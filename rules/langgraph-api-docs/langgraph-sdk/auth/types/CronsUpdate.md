# CronsUpdate

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/auth/types/CronsUpdate)

Payload for updating a cron job.

???+ example "Examples"

    ```python
    update_params = {
        "cron_id": UUID("123e4567-e89b-12d3-a456-426614174000"),
        "payload": {"key": "value"},
        "schedule": "0 0 * * *"
    }
    ```

## Signature

```python
CronsUpdate()
```

## Extends

- `typing.TypedDict`

## Constructors

```python
__init__(
    cron_id: UUID,
    payload: dict[str, typing.Any] | None,
    schedule: str | None,
)
```

| Name | Type |
|------|------|
| `cron_id` | `UUID` |
| `payload` | `dict[str, typing.Any] \| None` |
| `schedule` | `str \| None` |


## Properties

- `cron_id`
- `payload`
- `schedule`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/auth/types.py#L810)