# StreamMux

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/stream/_mux/StreamMux)

Central event dispatcher for the streaming infrastructure.

Owns the main event log and routes events through a transformer
pipeline. StreamChannels with a name discovered in transformer
projections are auto-wired so that every `push()` also injects a
`ProtocolEvent` into the main log. StreamChannels without a name
are local-only.

Pass `is_async=True` when the mux will be consumed via async
iteration (`handler.astream()`). All StreamChannel instances
discovered during registration are automatically bound to the
matching mode.

## Signature

```python
StreamMux(
    self,
    transformers: list[StreamTransformer] | None = None,
    *,
    is_async: bool = False,
    factories: list[TransformerFactory] | None = None,
    scope: tuple[str, ...] = (),
    _assign_seq: bool = True,
)
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `transformers` | `list[StreamTransformer] \| None` | No | Already-built transformer instances. Registered only on this mux — they are NOT cloned into child mini-muxes built by `_make_child`. Use `factories` for transformers that should propagate to nested scopes. (default: `None`) |
| `is_async` | `bool` | No | True for async dispatch (`apush` / `aclose` / `afail`), False for the sync path. (default: `False`) |
| `factories` | `list[TransformerFactory] \| None` | No | One-argument callables `(scope) -> StreamTransformer`. Called once with this mux's `scope` here, and cloned again per child scope by `_make_child` so each sub-mux gets fresh instances. (default: `None`) |
| `scope` | `tuple[str, ...]` | No | The namespace the mux operates within. The root mux is `()`. (default: `()`) |
| `_assign_seq` | `bool` | No | Internal flag for child muxes. Root muxes assign monotonic `seq` numbers when appending to their main event log; child muxes share forwarded event objects and must not mutate their envelopes. (default: `True`) |

## Constructors

```python
__init__(
    self,
    transformers: list[StreamTransformer] | None = None,
    *,
    is_async: bool = False,
    factories: list[TransformerFactory] | None = None,
    scope: tuple[str, ...] = (),
    _assign_seq: bool = True,
) -> None
```

| Name | Type |
|------|------|
| `transformers` | `list[StreamTransformer] \| None` |
| `is_async` | `bool` |
| `factories` | `list[TransformerFactory] \| None` |
| `scope` | `tuple[str, ...]` |
| `_assign_seq` | `bool` |


## Properties

- `is_async`
- `scope`
- `extensions`
- `native_keys`

## Methods

- [`transformer_by_key()`](https://reference.langchain.com/python/langgraph/stream/_mux/StreamMux/transformer_by_key)
- [`bind_pump()`](https://reference.langchain.com/python/langgraph/stream/_mux/StreamMux/bind_pump)
- [`bind_apump()`](https://reference.langchain.com/python/langgraph/stream/_mux/StreamMux/bind_apump)
- [`push()`](https://reference.langchain.com/python/langgraph/stream/_mux/StreamMux/push)
- [`close()`](https://reference.langchain.com/python/langgraph/stream/_mux/StreamMux/close)
- [`fail()`](https://reference.langchain.com/python/langgraph/stream/_mux/StreamMux/fail)
- [`apush()`](https://reference.langchain.com/python/langgraph/stream/_mux/StreamMux/apush)
- [`aclose()`](https://reference.langchain.com/python/langgraph/stream/_mux/StreamMux/aclose)
- [`afail()`](https://reference.langchain.com/python/langgraph/stream/_mux/StreamMux/afail)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/stream/_mux.py#L26)