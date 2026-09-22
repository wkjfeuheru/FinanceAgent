# ToolCallHandle

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/_async/stream/ToolCallHandle)

Async handle for one root-scope tool call.

## Signature

```python
ToolCallHandle(
    self,
    *,
    tool_call_id: str,
    name: str,
    input: Any = None,
    namespace: list[str] | None = None,
    max_queue_size: int = 1024,
)
```

## Constructors

```python
__init__(
    self,
    *,
    tool_call_id: str,
    name: str,
    input: Any = None,
    namespace: list[str] | None = None,
    max_queue_size: int = 1024,
) -> None
```

| Name | Type |
|------|------|
| `tool_call_id` | `str` |
| `name` | `str` |
| `input` | `Any` |
| `namespace` | `list[str] \| None` |
| `max_queue_size` | `int` |


## Properties

- `tool_call_id`
- `name`
- `input`
- `namespace`
- `done`
- `error`
- `output`
- `deltas`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/_async/stream.py#L967)