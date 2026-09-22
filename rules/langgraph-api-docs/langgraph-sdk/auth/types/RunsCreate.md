# RunsCreate

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/auth/types/RunsCreate)

Payload for creating a run.

???+ example "Examples"

    ```python
    create_params = {
        "assistant_id": UUID("123e4567-e89b-12d3-a456-426614174000"),
        "thread_id": UUID("123e4567-e89b-12d3-a456-426614174001"),
        "run_id": UUID("123e4567-e89b-12d3-a456-426614174002"),
        "status": "pending",
        "metadata": {"owner": "user123"},
        "prevent_insert_if_inflight": True,
        "multitask_strategy": "reject",
        "if_not_exists": "create",
        "after_seconds": 10,
        "kwargs": {"key": "value"},
        "action": "interrupt"
    }
    ```

## Signature

```python
RunsCreate()
```

## Extends

- `typing.TypedDict`

## Constructors

```python
__init__(
    assistant_id: UUID | None,
    thread_id: UUID | None,
    run_id: UUID | None,
    status: RunStatus | None,
    metadata: MetadataInput,
    prevent_insert_if_inflight: bool,
    multitask_strategy: MultitaskStrategy,
    if_not_exists: IfNotExists,
    after_seconds: int,
    kwargs: dict[str, typing.Any],
    action: typing.Literal['interrupt', 'rollback'] | None,
)
```

| Name | Type |
|------|------|
| `assistant_id` | `UUID \| None` |
| `thread_id` | `UUID \| None` |
| `run_id` | `UUID \| None` |
| `status` | `RunStatus \| None` |
| `metadata` | `MetadataInput` |
| `prevent_insert_if_inflight` | `bool` |
| `multitask_strategy` | `MultitaskStrategy` |
| `if_not_exists` | `IfNotExists` |
| `after_seconds` | `int` |
| `kwargs` | `dict[str, typing.Any]` |
| `action` | `typing.Literal['interrupt', 'rollback'] \| None` |


## Properties

- `assistant_id`
- `thread_id`
- `run_id`
- `status`
- `metadata`
- `prevent_insert_if_inflight`
- `multitask_strategy`
- `if_not_exists`
- `after_seconds`
- `kwargs`
- `action`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/auth/types.py#L543)