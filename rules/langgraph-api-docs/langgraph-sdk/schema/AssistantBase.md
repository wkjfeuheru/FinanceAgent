# AssistantBase

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/schema/AssistantBase)

Base model for an assistant.

## Signature

```python
AssistantBase()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    assistant_id: str,
    graph_id: str,
    config: Config,
    context: Context,
    created_at: datetime,
    metadata: Json,
    version: int,
    name: str,
    description: str | None,
)
```

| Name | Type |
|------|------|
| `assistant_id` | `str` |
| `graph_id` | `str` |
| `config` | `Config` |
| `context` | `Context` |
| `created_at` | `datetime` |
| `metadata` | `Json` |
| `version` | `int` |
| `name` | `str` |
| `description` | `str \| None` |


## Properties

- `assistant_id`
- `graph_id`
- `config`
- `context`
- `created_at`
- `metadata`
- `version`
- `name`
- `description`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/schema.py#L246)