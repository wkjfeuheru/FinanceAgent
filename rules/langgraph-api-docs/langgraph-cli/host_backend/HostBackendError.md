# HostBackendError

> **Class** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/host_backend/HostBackendError)

Raised when the host backend returns an error response.

## Signature

```python
HostBackendError(
    self,
    message: str,
    status_code: int | None = None,
)
```

## Extends

- `click.ClickException`

## Constructors

```python
__init__(
    self,
    message: str,
    status_code: int | None = None,
)
```

| Name | Type |
|------|------|
| `message` | `str` |
| `status_code` | `int \| None` |


## Properties

- `status_code`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/host_backend.py#L11)