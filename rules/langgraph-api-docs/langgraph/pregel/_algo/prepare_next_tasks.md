# prepare_next_tasks

> **Function** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/pregel/_algo/prepare_next_tasks)

Prepare the set of tasks that will make up the next Pregel step.

## Signature

```python
prepare_next_tasks(
    checkpoint: Checkpoint,
    pending_writes: list[PendingWrite],
    processes: Mapping[str, PregelNode],
    channels: Mapping[str, BaseChannel],
    managed: ManagedValueMapping,
    config: RunnableConfig,
    step: int,
    stop: int,
    *,
    for_execution: bool,
    store: BaseStore | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    manager: None | ParentRunManager | AsyncParentRunManager = None,
    trigger_to_nodes: Mapping[str, Sequence[str]] | None = None,
    updated_channels: set[str] | None = None,
    retry_policy: Sequence[RetryPolicy] = (),
    cache_policy: CachePolicy | None = None,
) -> dict[str, PregelTask] | dict[str, PregelExecutableTask]
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `checkpoint` | `Checkpoint` | Yes | The current checkpoint. |
| `pending_writes` | `list[PendingWrite]` | Yes | The list of pending writes. |
| `processes` | `Mapping[str, PregelNode]` | Yes | The mapping of process names to PregelNode instances. |
| `channels` | `Mapping[str, BaseChannel]` | Yes | The mapping of channel names to BaseChannel instances. |
| `managed` | `ManagedValueMapping` | Yes | The mapping of managed value names to functions. |
| `config` | `RunnableConfig` | Yes | The `Runnable` configuration. |
| `step` | `int` | Yes | The current step. |
| `for_execution` | `bool` | Yes | Whether the tasks are being prepared for execution. |
| `store` | `BaseStore \| None` | No | An instance of BaseStore to make it available for usage within tasks. (default: `None`) |
| `checkpointer` | `BaseCheckpointSaver \| None` | No | `Checkpointer` instance used for saving checkpoints. (default: `None`) |
| `manager` | `None \| ParentRunManager \| AsyncParentRunManager` | No | The parent run manager to use for the tasks. (default: `None`) |
| `trigger_to_nodes` | `Mapping[str, Sequence[str]] \| None` | No | Optional: Mapping of channel names to the set of nodes that are can be triggered by that channel. (default: `None`) |
| `updated_channels` | `set[str] \| None` | No | Optional. Set of channel names that have been updated during the previous step. Using in conjunction with trigger_to_nodes to speed up the process of determining which nodes should be triggered in the next step. (default: `None`) |

## Returns

`dict[str, PregelTask] | dict[str, PregelExecutableTask]`

A dictionary of tasks to be executed. The keys are the task ids and the values

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/pregel/_algo.py#L392)