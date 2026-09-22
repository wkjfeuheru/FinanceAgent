# AssistantsRead

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/auth/types/AssistantsRead)

Payload for reading an assistant.

???+ example "Examples"

    ```python
    read_params = {
        "assistant_id": UUID("123e4567-e89b-12d3-a456-426614174000"),
        "metadata": {"owner": "user123"}
    }
    ```

## Signature

```python
AssistantsRead()
```

## Extends

- `typing.TypedDict`

## Constructors

```python
__init__(
    assistant_id: UUID,
    metadata: MetadataInput,
)
```

| Name | Type |
|------|------|
| `assistant_id` | `UUID` |
| `metadata` | `MetadataInput` |


## Properties

- `assistant_id`
- `metadata`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/auth/types.py#L638)