# InterruptPayload

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/_sync/stream/InterruptPayload)

Payload surfaced when the server requests human input for a thread.

## Signature

```python
InterruptPayload()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    interrupt_id: str,
    value: Any,
    namespace: list[str],
)
```

| Name | Type |
|------|------|
| `interrupt_id` | `str` |
| `value` | `Any` |
| `namespace` | `list[str]` |


## Properties

- `interrupt_id`
- `value`
- `namespace`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/_sync/stream.py#L46)