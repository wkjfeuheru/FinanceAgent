# map_command

> **Function** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/pregel/_io/map_command)

Map input chunk to a sequence of pending writes in the form (channel, value).

## Signature

```python
map_command(
    cmd: Command,
) -> Iterator[tuple[str, str, Any]]
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/pregel/_io.py#L56)