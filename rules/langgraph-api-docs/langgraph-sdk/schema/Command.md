# Command

> **Class** in `langgraph_sdk`

📖 [View in docs](https://reference.langchain.com/python/langgraph-sdk/schema/Command)

Represents one or more commands to control graph execution flow and state.

This type defines the control commands that can be returned by nodes to influence
graph execution. It lets you navigate to other nodes, update graph state,
and resume from interruptions.

## Signature

```python
Command()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    goto: Send | str | Sequence[Send | str],
    update: dict[str, Any] | Sequence[tuple[str, Any]],
    resume: Any,
)
```

| Name | Type |
|------|------|
| `goto` | `Send \| str \| Sequence[Send \| str]` |
| `update` | `dict[str, Any] \| Sequence[tuple[str, Any]]` |
| `resume` | `Any` |


## Properties

- `goto`
- `update`
- `resume`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/13f2ecc84bdf257af19b370a2f03a0f02d15674d/libs/sdk-py/langgraph_sdk/schema.py#L890)