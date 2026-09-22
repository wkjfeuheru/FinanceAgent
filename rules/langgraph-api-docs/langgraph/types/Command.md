# Command

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/types/Command)

One or more commands to update the graph's state and send messages to nodes.

## Signature

```python
Command(
    self,
    *,
    graph: str | None = None,
    update: Any | None = None,
    resume: dict[str, Any] | Any | None = None,
    goto: Send | Sequence[Send | N] | N = (),
)
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `graph` | `str \| None` | No | Graph to send the command to. Supported values are:  - `None`: the current graph - `Command.PARENT`: closest parent graph (default: `None`) |
| `update` | `Any \| None` | No | Update to apply to the graph's state. (default: `None`) |
| `resume` | `dict[str, Any] \| Any \| None` | No | Value to resume execution with. To be used together with [`interrupt()`][langgraph.types.interrupt]. Can be one of the following:  - Mapping of interrupt ids to resume values - A single value with which to resume the next interrupt (default: `None`) |
| `goto` | `Send \| Sequence[Send \| N] \| N` | No | Can be one of the following:  - Name of the node to navigate to next (any node that belongs to the specified `graph`) - Sequence of node names to navigate to next - `Send` object (to execute a node with the input provided) - Sequence of `Send` objects (default: `()`) |

## Extends

- `Generic[N]`
- `ToolOutputMixin`

## Constructors

```python
__init__(
    self,
    *,
    graph: str | None = None,
    update: Any | None = None,
    resume: dict[str, Any] | Any | None = None,
    goto: Send | Sequence[Send | N] | N = (),
) -> None
```

| Name | Type |
|------|------|
| `graph` | `str \| None` |
| `update` | `Any \| None` |
| `resume` | `dict[str, Any] \| Any \| None` |
| `goto` | `Send \| Sequence[Send \| N] \| N` |


## Properties

- `graph`
- `update`
- `resume`
- `goto`
- `PARENT`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/types.py#L758)