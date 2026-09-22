# DataDecoder

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/stream/decoders/DataDecoder)

Yields `params.data` from events of a single `method`.

Covers the channels whose projection is just "emit the payload": `values`,
`updates`, `checkpoints`, `tasks` — the SDK analog of local's
`Values`/`Updates`/`Checkpoints`/`TasksTransformer`, all of which push
`params["data"]` unchanged. The REST-state seeding for `values` stays at
the projection layer; it is a one-shot pre-stream fetch, not part of the
event state machine.

## Signature

```python
DataDecoder(
    self,
    method: str,
    namespace: list[str] | None = None,
)
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `method` | `str` | Yes | The protocol `method` this decoder consumes. |
| `namespace` | `list[str] \| None` | No | When not `None`, events whose namespace differs are ignored (scope filter, mirroring the local transformers' `namespace != scope` check). `None` consumes every namespace — the historical `values` projection behavior, where subscription scoping is handled upstream. (default: `None`) |

## Constructors

```python
__init__(
    self,
    method: str,
    namespace: list[str] | None = None,
)
```

| Name | Type |
|------|------|
| `method` | `str` |
| `namespace` | `list[str] \| None` |


## Methods

- [`feed()`](https://reference.langchain.com/python/langgraph-sdk/stream/decoders/DataDecoder/feed)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/stream/decoders.py#L106)