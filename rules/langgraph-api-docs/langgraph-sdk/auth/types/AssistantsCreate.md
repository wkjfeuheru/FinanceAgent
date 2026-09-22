# AssistantsCreate

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/auth/types/AssistantsCreate)

Payload for creating an assistant.

???+ example "Examples"

    ```python
    create_params = {
        "assistant_id": UUID("123e4567-e89b-12d3-a456-426614174000"),
        "graph_id": "graph123",
        "config": {"tags": ["tag1", "tag2"]},
        "context": {"key": "value"},
        "metadata": {"owner": "user123"},
        "if_exists": "do_nothing",
        "name": "Assistant 1"
    }
    ```

## Signature

```python
AssistantsCreate()
```

## Extends

- `typing.TypedDict`

## Constructors

```python
__init__(
    assistant_id: UUID,
    graph_id: str,
    config: dict[str, typing.Any],
    context: dict[str, typing.Any],
    metadata: MetadataInput,
    if_exists: OnConflictBehavior,
    name: str,
)
```

| Name | Type |
|------|------|
| `assistant_id` | `UUID` |
| `graph_id` | `str` |
| `config` | `dict[str, typing.Any]` |
| `context` | `dict[str, typing.Any]` |
| `metadata` | `MetadataInput` |
| `if_exists` | `OnConflictBehavior` |
| `name` | `str` |


## Properties

- `assistant_id`
- `graph_id`
- `config`
- `context`
- `metadata`
- `if_exists`
- `name`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/auth/types.py#L599)