# create_model

> **Function** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/_internal/_pydantic/create_model)

Create a pydantic model with the given field definitions.

## Signature

```python
create_model(
    model_name: str,
    *,
    field_definitions: dict[str, Any] | None = None,
    root: Any | None = None,
) -> type[BaseModel]
```

## Description

**Attention:**

Please do not use outside of langchain packages. This API
is subject to change at any time.

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `model_name` | `str` | Yes | The name of the model. |
| `module_name` | `unknown` | Yes | The name of the module where the model is defined. This is used by Pydantic to resolve any forward references. |
| `field_definitions` | `dict[str, Any] \| None` | No | The field definitions for the model. (default: `None`) |
| `root` | `Any \| None` | No | Type for a root model (RootModel) (default: `None`) |

## Returns

`type[BaseModel]`

Type[BaseModel]: The created model.

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/_internal/_pydantic.py#L181)