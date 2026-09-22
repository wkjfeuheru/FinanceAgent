# AssistantsDelete

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/auth/types/AssistantsDelete)

Payload for deleting an assistant.

???+ example "Examples"

    ```python
    delete_params = {
        "assistant_id": UUID("123e4567-e89b-12d3-a456-426614174000")
    }
    ```

## Signature

```python
AssistantsDelete()
```

## Extends

- `typing.TypedDict`

## Constructors

```python
__init__(
    assistant_id: UUID,
)
```

| Name | Type |
|------|------|
| `assistant_id` | `UUID` |


## Properties

- `assistant_id`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/auth/types.py#L698)