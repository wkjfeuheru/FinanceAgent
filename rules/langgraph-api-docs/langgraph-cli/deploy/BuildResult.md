# BuildResult

> **Class** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/deploy/BuildResult)

Captures the outcome of a build stage so the shared wait tail can be
parameterized identically for both local and remote builds.

## Signature

```python
BuildResult(
    self,
    updated: dict = dict(),
    progress_message: str = '',
    timeout_seconds: int = 300,
    poll_interval_seconds: int = 1,
    no_result_message: str = 'Deployment updated',
    on_poll: Callable[[str, str, Callable[[str], None]], None] | None = None,
    on_interrupt: Callable[[str], None] | None = None,
    show_build_logs_on_failure: bool = False,
)
```

## Constructors

```python
__init__(
    self,
    updated: dict = dict(),
    progress_message: str = '',
    timeout_seconds: int = 300,
    poll_interval_seconds: int = 1,
    no_result_message: str = 'Deployment updated',
    on_poll: Callable[[str, str, Callable[[str], None]], None] | None = None,
    on_interrupt: Callable[[str], None] | None = None,
    show_build_logs_on_failure: bool = False,
) -> None
```

| Name | Type |
|------|------|
| `updated` | `dict` |
| `progress_message` | `str` |
| `timeout_seconds` | `int` |
| `poll_interval_seconds` | `int` |
| `no_result_message` | `str` |
| `on_poll` | `Callable[[str, str, Callable[[str], None]], None] \| None` |
| `on_interrupt` | `Callable[[str], None] \| None` |
| `show_build_logs_on_failure` | `bool` |


## Properties

- `updated`
- `progress_message`
- `timeout_seconds`
- `poll_interval_seconds`
- `no_result_message`
- `on_poll`
- `on_interrupt`
- `show_build_logs_on_failure`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/deploy.py#L104)