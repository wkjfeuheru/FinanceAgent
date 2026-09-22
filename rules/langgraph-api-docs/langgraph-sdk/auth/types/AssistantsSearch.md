# AssistantsSearch

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/auth/types/AssistantsSearch)

Payload for searching assistants.

???+ example "Examples"

    ```python
    search_params = {
        "graph_id": "graph123",
        "metadata": {"owner": "user123"},
        "limit": 10,
        "offset": 0
    }
    ```

## Signature

```python
AssistantsSearch()
```

## Extends

- `typing.TypedDict`

## Constructors

```python
__init__(
    graph_id: str | None,
    metadata: MetadataInput,
    limit: int,
    offset: int,
)
```

| Name | Type |
|------|------|
| `graph_id` | `str \| None` |
| `metadata` | `MetadataInput` |
| `limit` | `int` |
| `offset` | `int` |


## Properties

- `graph_id`
- `metadata`
- `limit`
- `offset`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/auth/types.py#L714)