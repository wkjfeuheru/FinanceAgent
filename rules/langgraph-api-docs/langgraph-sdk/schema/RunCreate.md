# RunCreate

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/schema/RunCreate)

Defines the parameters for initiating a background run.

## Signature

```python
RunCreate()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    thread_id: str | None,
    assistant_id: str,
    input: dict | None,
    metadata: dict | None,
    config: Config | None,
    context: Context | None,
    checkpoint_id: str | None,
    interrupt_before: list[str] | None,
    interrupt_after: list[str] | None,
    webhook: str | None,
    multitask_strategy: MultitaskStrategy | None,
)
```

| Name | Type |
|------|------|
| `thread_id` | `str \| None` |
| `assistant_id` | `str` |
| `input` | `dict \| None` |
| `metadata` | `dict \| None` |
| `config` | `Config \| None` |
| `context` | `Context \| None` |
| `checkpoint_id` | `str \| None` |
| `interrupt_before` | `list[str] \| None` |
| `interrupt_after` | `list[str] \| None` |
| `webhook` | `str \| None` |
| `multitask_strategy` | `MultitaskStrategy \| None` |


## Properties

- `thread_id`
- `assistant_id`
- `input`
- `metadata`
- `config`
- `context`
- `checkpoint_id`
- `interrupt_before`
- `interrupt_after`
- `webhook`
- `multitask_strategy`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/schema.py#L522)