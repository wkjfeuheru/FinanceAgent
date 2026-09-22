# monitor_stream

> **Function** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/exec/monitor_stream)

## Signature

```python
monitor_stream(
    stream: asyncio.StreamReader,
    collect: bool = False,
    display: bool = False,
    on_line: Callable[[str], bool | None] | None = None,
) -> bytearray | None
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/exec.py#L126)