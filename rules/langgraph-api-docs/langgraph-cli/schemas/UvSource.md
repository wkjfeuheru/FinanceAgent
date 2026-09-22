# UvSource

> **Class** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/schemas/UvSource)

Deployment source rooted at a uv project or workspace.

## Signature

```python
UvSource()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    kind: Required[Literal['uv']],
    root: str,
    package: str,
)
```

| Name | Type |
|------|------|
| `kind` | `Required[Literal['uv']]` |
| `root` | `str` |
| `package` | `str` |


## Properties

- `kind`
- `root`
- `package`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/schemas.py#L593)