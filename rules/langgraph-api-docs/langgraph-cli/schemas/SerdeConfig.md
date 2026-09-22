# SerdeConfig

> **Class** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/schemas/SerdeConfig)

Configuration for the built-in serde, which handles checkpointing of state.

If omitted, no serde is set up (the object store will still be present, however).

## Signature

```python
SerdeConfig()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    allowed_json_modules: list[list[str]] | bool | None,
    allowed_msgpack_modules: list[list[str]] | bool | None,
    pickle_fallback: bool,
)
```

| Name | Type |
|------|------|
| `allowed_json_modules` | `list[list[str]] \| bool \| None` |
| `allowed_msgpack_modules` | `list[list[str]] \| bool \| None` |
| `pickle_fallback` | `bool` |


## Properties

- `allowed_json_modules`
- `allowed_msgpack_modules`
- `pickle_fallback`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/schemas.py#L127)