# StreamMessagesHandler

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/pregel/_messages/StreamMessagesHandler)

A callback handler that implements stream_mode=messages.

Collects messages from:
(1) chat model stream events; and
(2) node outputs.

## Signature

```python
StreamMessagesHandler(
    self,
    stream: Callable[[StreamChunk], None],
    subgraphs: bool,
    *,
    parent_ns: tuple[str, ...] | None = None,
)
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `stream` | `Callable[[StreamChunk], None]` | Yes | A callable that takes a StreamChunk and emits it. |
| `subgraphs` | `bool` | Yes | Whether to emit messages from subgraphs. |
| `parent_ns` | `tuple[str, ...] \| None` | No | The namespace where the handler was created. We keep track of this namespace to allow calls to subgraphs that were explicitly requested as a stream with `messages` mode configured. (default: `None`) |

## Extends

- `BaseCallbackHandler`
- `_StreamingCallbackHandler`

## Constructors

```python
__init__(
    self,
    stream: Callable[[StreamChunk], None],
    subgraphs: bool,
    *,
    parent_ns: tuple[str, ...] | None = None,
) -> None
```

| Name | Type |
|------|------|
| `stream` | `Callable[[StreamChunk], None]` |
| `subgraphs` | `bool` |
| `parent_ns` | `tuple[str, ...] \| None` |


## Properties

- `run_inline`
- `stream`
- `subgraphs`
- `metadata`
- `seen`
- `parent_ns`

## Methods

- [`tap_output_aiter()`](https://reference.langchain.com/python/langgraph/pregel/_messages/StreamMessagesHandler/tap_output_aiter)
- [`tap_output_iter()`](https://reference.langchain.com/python/langgraph/pregel/_messages/StreamMessagesHandler/tap_output_iter)
- [`on_chat_model_start()`](https://reference.langchain.com/python/langgraph/pregel/_messages/StreamMessagesHandler/on_chat_model_start)
- [`on_llm_new_token()`](https://reference.langchain.com/python/langgraph/pregel/_messages/StreamMessagesHandler/on_llm_new_token)
- [`on_llm_end()`](https://reference.langchain.com/python/langgraph/pregel/_messages/StreamMessagesHandler/on_llm_end)
- [`on_llm_error()`](https://reference.langchain.com/python/langgraph/pregel/_messages/StreamMessagesHandler/on_llm_error)
- [`on_chain_start()`](https://reference.langchain.com/python/langgraph/pregel/_messages/StreamMessagesHandler/on_chain_start)
- [`on_chain_end()`](https://reference.langchain.com/python/langgraph/pregel/_messages/StreamMessagesHandler/on_chain_end)
- [`on_chain_error()`](https://reference.langchain.com/python/langgraph/pregel/_messages/StreamMessagesHandler/on_chain_error)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/pregel/_messages.py#L49)