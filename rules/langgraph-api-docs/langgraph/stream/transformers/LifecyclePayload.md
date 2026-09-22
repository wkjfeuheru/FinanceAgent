# LifecyclePayload

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/stream/transformers/LifecyclePayload)

Payload of a lifecycle event surfaced on the `lifecycle` channel.

Auto-forwarded as `lifecycle` protocol events (no `custom:` prefix
because `LifecycleTransformer` is a native transformer) so remote
SDK clients receive the same data in-process consumers see via
`run.lifecycle`.

## Signature

```python
LifecyclePayload()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    event: SubgraphStatus,
    namespace: list[str],
    graph_name: NotRequired[str],
    trigger_call_id: NotRequired[str],
    cause: NotRequired[LifecycleCause],
    error: NotRequired[str],
)
```

| Name | Type |
|------|------|
| `event` | `SubgraphStatus` |
| `namespace` | `list[str]` |
| `graph_name` | `NotRequired[str]` |
| `trigger_call_id` | `NotRequired[str]` |
| `cause` | `NotRequired[LifecycleCause]` |
| `error` | `NotRequired[str]` |


## Properties

- `event`
- `namespace`
- `graph_name`
- `trigger_call_id`
- `cause`
- `error`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/stream/transformers.py#L356)