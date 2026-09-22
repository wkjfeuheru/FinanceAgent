# AssistantsUpdate

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/auth/types/AssistantsUpdate)

Payload for updating an assistant.

???+ example "Examples"

    ```python
    update_params = {
        "assistant_id": UUID("123e4567-e89b-12d3-a456-426614174000"),
        "graph_id": "graph123",
        "config": {"tags": ["tag1", "tag2"]},
        "context": {"key": "value"},
        "metadata": {"owner": "user123"},
        "name": "Assistant 1",
        "version": 1
    }
    ```

## Signature

```python
AssistantsUpdate()
```

## Extends

- `typing.TypedDict`

## Constructors

```python
__init__(
    assistant_id: UUID,
    graph_id: str | None,
    config: dict[str, typing.Any],
    context: dict[str, typing.Any],
    metadata: MetadataInput,
    name: str | None,
    version: int | None,
)
```

| Name | Type |
|------|------|
| `assistant_id` | `UUID` |
| `graph_id` | `str \| None` |
| `config` | `dict[str, typing.Any]` |
| `context` | `dict[str, typing.Any]` |
| `metadata` | `MetadataInput` |
| `name` | `str \| None` |
| `version` | `int \| None` |


## Properties

- `assistant_id`
- `graph_id`
- `config`
- `context`
- `metadata`
- `name`
- `version`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/auth/types.py#L658)