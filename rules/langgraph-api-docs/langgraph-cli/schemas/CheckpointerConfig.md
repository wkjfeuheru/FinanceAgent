# CheckpointerConfig

> **Class** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/schemas/CheckpointerConfig)

Configuration for the built-in checkpointer, which handles checkpointing of state.

If omitted, no checkpointer is set up (the object store will still be present, however).

## Signature

```python
CheckpointerConfig()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    path: str,
    ttl: ThreadTTLConfig | None,
    serde: SerdeConfig | None,
)
```

| Name | Type |
|------|------|
| `path` | `str` |
| `ttl` | `ThreadTTLConfig \| None` |
| `serde` | `SerdeConfig \| None` |


## Properties

- `path`
- `ttl`
- `serde`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/schemas.py#L193)