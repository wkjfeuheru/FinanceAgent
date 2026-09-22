# RunnableCallable

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/_internal/_runnable/RunnableCallable)

A much simpler version of RunnableLambda that requires sync and async functions.

## Signature

```python
RunnableCallable(
    self,
    func: Callable[..., Any | Runnable] | None,
    afunc: Callable[..., Awaitable[Any | Runnable]] | None = None,
    *,
    name: str | None = None,
    tags: Sequence[str] | None = None,
    trace: bool = True,
    recurse: bool = True,
    explode_args: bool = False,
    **kwargs: Any = {},
)
```

## Extends

- `Runnable`

## Constructors

```python
__init__(
    self,
    func: Callable[..., Any | Runnable] | None,
    afunc: Callable[..., Awaitable[Any | Runnable]] | None = None,
    *,
    name: str | None = None,
    tags: Sequence[str] | None = None,
    trace: bool = True,
    recurse: bool = True,
    explode_args: bool = False,
    **kwargs: Any = {},
) -> None
```

| Name | Type |
|------|------|
| `func` | `Callable[..., Any \| Runnable] \| None` |
| `afunc` | `Callable[..., Awaitable[Any \| Runnable]] \| None` |
| `name` | `str \| None` |
| `tags` | `Sequence[str] \| None` |
| `trace` | `bool` |
| `recurse` | `bool` |
| `explode_args` | `bool` |


## Properties

- `name`
- `func`
- `afunc`
- `tags`
- `kwargs`
- `trace`
- `recurse`
- `explode_args`
- `func_accepts`

## Methods

- [`invoke()`](https://reference.langchain.com/python/langgraph/_internal/_runnable/RunnableCallable/invoke)
- [`ainvoke()`](https://reference.langchain.com/python/langgraph/_internal/_runnable/RunnableCallable/ainvoke)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/_internal/_runnable.py#L278)