# Progress

> **Class** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/progress/Progress)

## Signature

```python
Progress(
    self,
    *,
    message = '',
    elapsed: bool = False,
    json_mode: bool = False,
)
```

## Constructors

```python
__init__(
    self,
    *,
    message = '',
    elapsed: bool = False,
    json_mode: bool = False,
)
```

| Name | Type |
|------|------|
| `message` | `unknown` |
| `elapsed` | `bool` |
| `json_mode` | `bool` |


## Properties

- `delay`
- `message`
- `spinner_generator`

## Methods

- [`spinning_cursor()`](https://reference.langchain.com/python/langgraph-cli/progress/Progress/spinning_cursor)
- [`spinner_iteration()`](https://reference.langchain.com/python/langgraph-cli/progress/Progress/spinner_iteration)
- [`spinner_task()`](https://reference.langchain.com/python/langgraph-cli/progress/Progress/spinner_task)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/progress.py#L7)