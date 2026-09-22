# Run

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/schema/Run)

Represents a single execution run.

## Signature

```python
Run()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    run_id: str,
    thread_id: str,
    assistant_id: str,
    created_at: datetime,
    updated_at: datetime,
    status: RunStatus,
    metadata: Json,
    multitask_strategy: MultitaskStrategy,
)
```

| Name | Type |
|------|------|
| `run_id` | `str` |
| `thread_id` | `str` |
| `assistant_id` | `str` |
| `created_at` | `datetime` |
| `updated_at` | `datetime` |
| `status` | `RunStatus` |
| `metadata` | `Json` |
| `multitask_strategy` | `MultitaskStrategy` |


## Properties

- `run_id`
- `thread_id`
- `assistant_id`
- `created_at`
- `updated_at`
- `status`
- `metadata`
- `multitask_strategy`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/schema.py#L362)