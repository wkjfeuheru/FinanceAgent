# NodeError

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/errors/NodeError)

Failure context passed to a node-level error handler.

Inject by adding a parameter typed `NodeError` to a handler registered via
`StateGraph.add_node(..., error_handler=...)`:

```python
def handler(state: State, error: NodeError) -> Command:
    return Command(update={"status": f"recovered from {error.node}: {error.error}"})
```

## Signature

```python
NodeError(
    self,
    node: str,
    error: BaseException,
)
```

## Constructors

```python
__init__(
    self,
    node: str,
    error: BaseException,
) -> None
```

| Name | Type |
|------|------|
| `node` | `str` |
| `error` | `BaseException` |


## Properties

- `node`
- `error`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/errors.py#L148)