# ChannelRead

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/pregel/_read/ChannelRead)

Implements the logic for reading state from CONFIG_KEY_READ.
Usable both as a runnable as well as a static method to call imperatively.

## Signature

```python
ChannelRead(
    self,
    channel: str | list[str],
    *,
    fresh: bool = False,
    mapper: Callable[[Any], Any] | None = None,
    tags: list[str] | None = None,
)
```

## Extends

- `RunnableCallable`

## Constructors

```python
__init__(
    self,
    channel: str | list[str],
    *,
    fresh: bool = False,
    mapper: Callable[[Any], Any] | None = None,
    tags: list[str] | None = None,
) -> None
```

| Name | Type |
|------|------|
| `channel` | `str \| list[str]` |
| `fresh` | `bool` |
| `mapper` | `Callable[[Any], Any] \| None` |
| `tags` | `list[str] \| None` |


## Properties

- `channel`
- `fresh`
- `mapper`

## Methods

- [`get_name()`](https://reference.langchain.com/python/langgraph/pregel/_read/ChannelRead/get_name)
- [`do_read()`](https://reference.langchain.com/python/langgraph/pregel/_read/ChannelRead/do_read)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/pregel/_read.py#L25)