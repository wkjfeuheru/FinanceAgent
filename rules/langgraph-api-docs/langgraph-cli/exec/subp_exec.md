# subp_exec

> **Function** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/exec/subp_exec)

## Signature

```python
subp_exec(
    cmd: str,
    *args: str = (),
    input: str | None = None,
    wait: float | None = None,
    verbose: bool = False,
    collect: bool = False,
    on_stdout: Callable[[str], bool | None] | None = None,
) -> tuple[str | None, str | None]
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/exec.py#L31)