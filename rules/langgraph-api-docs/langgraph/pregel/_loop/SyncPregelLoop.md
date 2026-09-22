# SyncPregelLoop

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/pregel/_loop/SyncPregelLoop)

## Signature

```python
SyncPregelLoop(
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
    trigger_to_nodes: Mapping[str, Sequence[str]],
    durability: Durability,
    manager: None | AsyncParentRunManager | ParentRunManager = None,
    interrupt_after: All | Sequence[str] = EMPTY_SEQ,
    interrupt_before: All | Sequence[str] = EMPTY_SEQ,
    input_keys: str | Sequence[str] = EMPTY_SEQ,
    output_keys: str | Sequence[str] = EMPTY_SEQ,
    stream_keys: str | Sequence[str] = EMPTY_SEQ,
    migrate_checkpoint: Callable[[Checkpoint], None] | None = None,
    retry_policy: Sequence[RetryPolicy] = (),
    cache_policy: CachePolicy | None = None,
    has_graph_lifecycle_callbacks: bool = False,
)
```

## Extends

- `PregelLoop`
- `AbstractContextManager`

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
    trigger_to_nodes: Mapping[str, Sequence[str]],
    durability: Durability,
    manager: None | AsyncParentRunManager | ParentRunManager = None,
    interrupt_after: All | Sequence[str] = EMPTY_SEQ,
    interrupt_before: All | Sequence[str] = EMPTY_SEQ,
    input_keys: str | Sequence[str] = EMPTY_SEQ,
    output_keys: str | Sequence[str] = EMPTY_SEQ,
    stream_keys: str | Sequence[str] = EMPTY_SEQ,
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
| `trigger_to_nodes` | `Mapping[str, Sequence[str]]` |
| `durability` | `Durability` |
| `manager` | `None \| AsyncParentRunManager \| ParentRunManager` |
| `interrupt_after` | `All \| Sequence[str]` |
| `interrupt_before` | `All \| Sequence[str]` |
| `input_keys` | `str \| Sequence[str]` |
| `output_keys` | `str \| Sequence[str]` |
| `stream_keys` | `str \| Sequence[str]` |
| `migrate_checkpoint` | `Callable[[Checkpoint], None] \| None` |
| `retry_policy` | `Sequence[RetryPolicy]` |
| `cache_policy` | `CachePolicy \| None` |
| `has_graph_lifecycle_callbacks` | `bool` |


## Properties

- `stack`
- `checkpointer_get_next_version`
- `checkpointer_put_writes`
- `checkpointer_put_writes_accepts_task_path`

## Methods

- [`match_cached_writes()`](https://reference.langchain.com/python/langgraph/pregel/_loop/SyncPregelLoop/match_cached_writes)
- [`accept_push()`](https://reference.langchain.com/python/langgraph/pregel/_loop/SyncPregelLoop/accept_push)
- [`schedule_error_handler()`](https://reference.langchain.com/python/langgraph/pregel/_loop/SyncPregelLoop/schedule_error_handler)
- [`put_writes()`](https://reference.langchain.com/python/langgraph/pregel/_loop/SyncPregelLoop/put_writes)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/pregel/_loop.py#L1469)