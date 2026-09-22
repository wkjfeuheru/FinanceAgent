# GraphSchema

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/schema/GraphSchema)

Defines the structure and properties of a graph.

## Signature

```python
GraphSchema()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    graph_id: str,
    input_schema: dict | None,
    output_schema: dict | None,
    state_schema: dict | None,
    config_schema: dict | None,
    context_schema: dict | None,
)
```

| Name | Type |
|------|------|
| `graph_id` | `str` |
| `input_schema` | `dict \| None` |
| `output_schema` | `dict \| None` |
| `state_schema` | `dict \| None` |
| `config_schema` | `dict \| None` |
| `context_schema` | `dict \| None` |


## Properties

- `graph_id`
- `input_schema`
- `output_schema`
- `state_schema`
- `config_schema`
- `context_schema`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/schema.py#L221)