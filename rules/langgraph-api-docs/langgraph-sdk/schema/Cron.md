# Cron

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/schema/Cron)

Represents a scheduled task.

## Signature

```python
Cron()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    cron_id: str,
    assistant_id: str,
    thread_id: str | None,
    on_run_completed: OnCompletionBehavior | None,
    end_time: datetime | None,
    schedule: str,
    timezone: str | None,
    created_at: datetime,
    updated_at: datetime,
    payload: dict,
    user_id: str | None,
    next_run_date: datetime | None,
    metadata: dict,
    enabled: bool,
)
```

| Name | Type |
|------|------|
| `cron_id` | `str` |
| `assistant_id` | `str` |
| `thread_id` | `str \| None` |
| `on_run_completed` | `OnCompletionBehavior \| None` |
| `end_time` | `datetime \| None` |
| `schedule` | `str` |
| `timezone` | `str \| None` |
| `created_at` | `datetime` |
| `updated_at` | `datetime` |
| `payload` | `dict` |
| `user_id` | `str \| None` |
| `next_run_date` | `datetime \| None` |
| `metadata` | `dict` |
| `enabled` | `bool` |


## Properties

- `cron_id`
- `assistant_id`
- `thread_id`
- `on_run_completed`
- `end_time`
- `schedule`
- `timezone`
- `created_at`
- `updated_at`
- `payload`
- `user_id`
- `next_run_date`
- `metadata`
- `enabled`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/schema.py#L383)