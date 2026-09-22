# AssistantsSearchResponse

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/schema/AssistantsSearchResponse)

Paginated response for assistant search results.

## Signature

```python
AssistantsSearchResponse()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    assistants: list[Assistant],
    next: str | None,
)
```

| Name | Type |
|------|------|
| `assistants` | `list[Assistant]` |
| `next` | `str \| None` |


## Properties

- `assistants`
- `next`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/schema.py#L282)