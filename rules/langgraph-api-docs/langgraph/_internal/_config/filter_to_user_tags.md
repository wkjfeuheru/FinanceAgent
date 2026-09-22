# filter_to_user_tags

> **Function** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/_internal/_config/filter_to_user_tags)

Drop langgraph's internal `seq:step:*` bookkeeping tags.

`seq:step:N` tags are added internally to mark sequence steps; everything
else (user-supplied tags and any other framework tags) is kept. Returns the
surviving tags, or `None` if none remain. Shared by the `messages` and
`tasks` stream handlers so both surface the same tag set on their metadata.

## Signature

```python
filter_to_user_tags(
    tags: Sequence[str] | None,
) -> list[str] | None
```

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/_internal/_config.py#L463)