# PregelLoop

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/pregel/_loop/PregelLoop)

## Signature

```python
PregelLoop(
    self,
    input: Any | None,
    *,
    stream: StreamProtocol | None,
    config: RunnableConfig,
    store: BaseStore | None,
    cache: BaseCache | None,
    checkpointer: BaseCheckpointSaver | None,
    nodes: Mapping[str, PregelNode],
    specs: Mapping[str, BaseChannel | ManagedValueSpec],
    input_keys: str | Sequence[str],
    output_keys: str | Sequence[str],
    stream_keys: str | Sequence[str],
    trigger_to_nodes: Mapping[str, Sequence[str]],
    durability: Durability,
    interrupt_after: All | Sequence[str] = EMPTY_SEQ,
    interrupt_before: All | Sequence[str] = EMPTY_SEQ,
    manager: None | AsyncParentRunManager | ParentRunManager = None,
    migrate_checkpoint: Callable[[Checkpoint], None] | None = None,
    retry_policy: Sequence[RetryPolicy] = (),
    cache_policy: CachePolicy | None = None,
    has_graph_lifecycle_callbacks: bool = False,
)
```

## Constructors

```python
__init__(
    self,
    input: Any | None,
    *,
    stream: StreamProtocol | None,
    config: RunnableConfig,
    store: BaseStore | None,
    cache: BaseCache | None,
    checkpointer: BaseCheckpointSaver | None,
    nodes: Mapping[str, PregelNode],
    specs: Mapping[str, BaseChannel | ManagedValueSpec],
    input_keys: str | Sequence[str],
    output_keys: str | Sequence[str],
    stream_keys: str | Sequence[str],
    trigger_to_nodes: Mapping[str, Sequence[str]],
    durability: Durability,
    interrupt_after: All | Sequence[str] = EMPTY_SEQ,
    interrupt_before: All | Sequence[str] = EMPTY_SEQ,
    manager: None | AsyncParentRunManager | ParentRunManager = None,
    migrate_checkpoint: Callable[[Checkpoint], None] | None = None,
    retry_policy: Sequence[RetryPolicy] = (),
    cache_policy: CachePolicy | None = None,
    has_graph_lifecycle_callbacks: bool = False,
) -> None
```

| Name | Type |
|------|------|
| `input` | `Any \| None` |
| `stream` | `StreamProtocol \| None` |
| `config` | `RunnableConfig` |
| `store` | `BaseStore \| None` |
| `cache` | `BaseCache \| None` |
| `checkpointer` | `BaseCheckpointSaver \| None` |
| `nodes` | `Mapping[str, PregelNode]` |
| `specs` | `Mapping[str, BaseChannel \| ManagedValueSpec]` |
| `input_keys` | `str \| Sequence[str]` |
| `output_keys` | `str \| Sequence[str]` |
| `stream_keys` | `str \| Sequence[str]` |
| `trigger_to_nodes` | `Mapping[str, Sequence[str]]` |
| `durability` | `Durability` |
| `interrupt_after` | `All \| Sequence[str]` |
| `interrupt_before` | `All \| Sequence[str]` |
| `manager` | `None \| AsyncParentRunManager \| ParentRunManager` |
| `migrate_checkpoint` | `Callable[[Checkpoint], None] \| None` |
| `retry_policy` | `Sequence[RetryPolicy]` |
| `cache_policy` | `CachePolicy \| None` |
| `has_graph_lifecycle_callbacks` | `bool` |


## Properties

- `config`
- `store`
- `stream`
- `step`
- `stop`
- `input`
- `cache`
- `checkpointer`
- `nodes`
- `specs`
- `input_keys`
- `output_keys`
- `stream_keys`
- `is_replaying`
- `is_nested`
- `manager`
- `interrupt_after`
- `interrupt_before`
- `durability`
- `retry_policy`
- `cache_policy`
- `checkpointer_get_next_version`
- `checkpointer_put_writes`
- `checkpointer_put_writes_accepts_task_path`
- `submit`
- `channels`
- `managed`
- `checkpoint`
- `checkpoint_id_saved`
- `checkpoint_ns`
- `checkpoint_config`
- `checkpoint_metadata`
- `checkpoint_pending_writes`
- `checkpoint_previous_versions`
- `prev_checkpoint_config`
- `status`
- `control`
- `tasks`
- `output`
- `updated_channels`
- `trigger_to_nodes`

## Methods

- [`put_writes()`](https://reference.langchain.com/python/langgraph/pregel/_loop/PregelLoop/put_writes)
- [`accept_push()`](https://reference.langchain.com/python/langgraph/pregel/_loop/PregelLoop/accept_push)
- [`schedule_error_handler()`](https://reference.langchain.com/python/langgraph/pregel/_loop/PregelLoop/schedule_error_handler)
- [`aschedule_error_handler()`](https://reference.langchain.com/python/langgraph/pregel/_loop/PregelLoop/aschedule_error_handler)
- [`tick()`](https://reference.langchain.com/python/langgraph/pregel/_loop/PregelLoop/tick)
- [`after_tick()`](https://reference.langchain.com/python/langgraph/pregel/_loop/PregelLoop/after_tick)
- [`match_cached_writes()`](https://reference.langchain.com/python/langgraph/pregel/_loop/PregelLoop/match_cached_writes)
- [`amatch_cached_writes()`](https://reference.langchain.com/python/langgraph/pregel/_loop/PregelLoop/amatch_cached_writes)
- [`output_writes()`](https://reference.langchain.com/python/langgraph/pregel/_loop/PregelLoop/output_writes)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/pregel/_loop.py#L158)