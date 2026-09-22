# RunnableSeq

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/_internal/_runnable/RunnableSeq)

Sequence of `Runnable`, where the output of each is the input of the next.

`RunnableSeq` is a simpler version of `RunnableSequence` that is internal to
LangGraph.

## Signature

```python
RunnableSeq(
    self,
    *steps: RunnableLike = (),
    name: str | None = None,
    trace_inputs: Callable[[Any], Any] | None = None,
)
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `steps` | `RunnableLike` | No | The steps to include in the sequence. (default: `()`) |
| `name` | `str \| None` | No | The name of the `Runnable`. (default: `None`) |

## Extends

- `Runnable`

## Constructors

```python
__init__(
    self,
    *steps: RunnableLike = (),
    name: str | None = None,
    trace_inputs: Callable[[Any], Any] | None = None,
) -> None
```

| Name | Type |
|------|------|
| `name` | `str \| None` |
| `trace_inputs` | `Callable[[Any], Any] \| None` |


## Properties

- `steps`
- `name`
- `trace_inputs`

## Methods

- [`invoke()`](https://reference.langchain.com/python/langgraph/_internal/_runnable/RunnableSeq/invoke)
- [`ainvoke()`](https://reference.langchain.com/python/langgraph/_internal/_runnable/RunnableSeq/ainvoke)
- [`stream()`](https://reference.langchain.com/python/langgraph/_internal/_runnable/RunnableSeq/stream)
- [`astream()`](https://reference.langchain.com/python/langgraph/_internal/_runnable/RunnableSeq/astream)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/_internal/_runnable.py#L563)