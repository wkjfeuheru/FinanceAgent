# entrypoint

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/func/entrypoint)

Define a LangGraph workflow using the `entrypoint` decorator.

### Function signature

The decorated function must accept a **single parameter**, which serves as the input
to the function. This input parameter can be of any type. Use a dictionary
to pass **multiple parameters** to the function.

### Injectable parameters

The decorated function can request access to additional parameters
that will be injected automatically at run time. These parameters include:

| Parameter        | Description                                                                                          |
|------------------|------------------------------------------------------------------------------------------------------|
| **`config`**     | A configuration object (aka `RunnableConfig`) that holds run-time configuration values.              |
| **`previous`**   | The previous return value for the given thread (available only when a checkpointer is provided).     |
| **`runtime`**    | A `Runtime` object that contains information about the current run, including context, store, writer |

The entrypoint decorator can be applied to sync functions or async functions.

### State management

The **`previous`** parameter can be used to access the return value of the previous
invocation of the entrypoint on the same thread id. This value is only available
when a checkpointer is provided.

If you want **`previous`** to be different from the return value, you can use the
`entrypoint.final` object to return a value while saving a different value to the
checkpoint.

## Signature

```python
entrypoint(
    self,
    checkpointer: BaseCheckpointSaver | None = None,
    store: BaseStore | None = None,
    cache: BaseCache | None = None,
    context_schema: type[ContextT] | None = None,
    cache_policy: CachePolicy | None = None,
    retry_policy: RetryPolicy | Sequence[RetryPolicy] | None = None,
    timeout: float | timedelta | TimeoutPolicy | None = None,
    **kwargs: Unpack[DeprecatedKwargs] = {},
)
```

## Description

!!! warning "`config_schema` Deprecated"
The `config_schema` parameter is deprecated in v0.6.0 and support will be removed in v2.0.0.
Please use `context_schema` instead to specify the schema for run-scoped context.

**Using entrypoint and tasks:**

```python
import time

from langgraph.func import entrypoint, task
from langgraph.types import interrupt, Command
from langgraph.checkpoint.memory import InMemorySaver

@task
def compose_essay(topic: str) -> str:
    time.sleep(1.0)  # Simulate slow operation
    return f"An essay about {topic}"

@entrypoint(checkpointer=InMemorySaver())
def review_workflow(topic: str) -> dict:
    """Manages the workflow for generating and reviewing an essay.

    The workflow includes:
    1. Generating an essay about the given topic.
    2. Interrupting the workflow for human review of the generated essay.

    Upon resuming the workflow, compose_essay task will not be re-executed
    as its result is cached by the checkpointer.

    Args:
        topic: The subject of the essay.

    Returns:
        dict: A dictionary containing the generated essay and the human review.
    """
    essay_future = compose_essay(topic)
    essay = essay_future.result()
    human_review = interrupt({
        "question": "Please provide a review",
        "essay": essay
    })
    return {
        "essay": essay,
        "review": human_review,
    }

# Example configuration for the workflow
config = {
    "configurable": {
        "thread_id": "some_thread"
    }
}

# Topic for the essay
topic = "cats"

# Stream the workflow to generate the essay and await human review
for result in review_workflow.stream(topic, config):
    print(result)

# Example human review provided after the interrupt
human_review = "This essay is great."

# Resume the workflow with the provided human review
for result in review_workflow.stream(Command(resume=human_review), config):
    print(result)
```

**Accessing the previous return value:**

When a checkpointer is enabled the function can access the previous return value
of the previous invocation on the same thread id.

```python
from typing import Optional

from langgraph.checkpoint.memory import MemorySaver

from langgraph.func import entrypoint

@entrypoint(checkpointer=InMemorySaver())
def my_workflow(input_data: str, previous: Optional[str] = None) -> str:
    return "world"

config = {"configurable": {"thread_id": "some_thread"}}
my_workflow.invoke("hello", config)
```

**Using `entrypoint.final` to save a value:**

The `entrypoint.final` object allows you to return a value while saving
a different value to the checkpoint. This value will be accessible
in the next invocation of the entrypoint via the `previous` parameter, as
long as the same thread id is used.

```python
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from langgraph.func import entrypoint

@entrypoint(checkpointer=InMemorySaver())
def my_workflow(
    number: int,
    *,
    previous: Any = None,
) -> entrypoint.final[int, int]:
    previous = previous or 0
    # This will return the previous value to the caller, saving
    # 2 * number to the checkpoint, which will be used in the next invocation
    # for the `previous` parameter.
    return entrypoint.final(value=previous, save=2 * number)

config = {"configurable": {"thread_id": "some_thread"}}

my_workflow.invoke(3, config)  # 0 (previous was None)
my_workflow.invoke(1, config)  # 6 (previous was 3 * 2 from the previous invocation)
```

## Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `checkpointer` | `BaseCheckpointSaver \| None` | No | Specify a checkpointer to create a workflow that can persist its state across runs. (default: `None`) |
| `store` | `BaseStore \| None` | No | A generalized key-value store. Some implementations may support semantic search capabilities through an optional `index` configuration. (default: `None`) |
| `cache` | `BaseCache \| None` | No | A cache to use for caching the results of the workflow. (default: `None`) |
| `context_schema` | `type[ContextT] \| None` | No | Specifies the schema for the context object that will be passed to the workflow. (default: `None`) |
| `cache_policy` | `CachePolicy \| None` | No | A cache policy to use for caching the results of the workflow. (default: `None`) |
| `retry_policy` | `RetryPolicy \| Sequence[RetryPolicy] \| None` | No | A retry policy (or list of policies) to use for the workflow in case of a failure. (default: `None`) |
| `timeout` | `float \| timedelta \| TimeoutPolicy \| None` | No | Timeout for each workflow attempt. A number or `timedelta` is a hard wall-clock cap and is not refreshed. Use `TimeoutPolicy` to configure both a wall-clock `run_timeout` and an `idle_timeout` refreshed by progress signals. For long-running work that doesn't naturally emit progress, call `runtime.heartbeat()` from inside the workflow. When the timeout fires, `NodeTimeoutError` is raised and the retry policy (if any) decides whether to retry. Supported only for async workflows; sync workflows cannot be safely cancelled in-process. (default: `None`) |

## Extends

- `Generic[ContextT]`

## Constructors

```python
__init__(
    self,
    checkpointer: BaseCheckpointSaver | None = None,
    store: BaseStore | None = None,
    cache: BaseCache | None = None,
    context_schema: type[ContextT] | None = None,
    cache_policy: CachePolicy | None = None,
    retry_policy: RetryPolicy | Sequence[RetryPolicy] | None = None,
    timeout: float | timedelta | TimeoutPolicy | None = None,
    **kwargs: Unpack[DeprecatedKwargs] = {},
) -> None
```

| Name | Type |
|------|------|
| `checkpointer` | `BaseCheckpointSaver \| None` |
| `store` | `BaseStore \| None` |
| `cache` | `BaseCache \| None` |
| `context_schema` | `type[ContextT] \| None` |
| `cache_policy` | `CachePolicy \| None` |
| `retry_policy` | `RetryPolicy \| Sequence[RetryPolicy] \| None` |
| `timeout` | `float \| timedelta \| TimeoutPolicy \| None` |


## Properties

- `checkpointer`
- `store`
- `cache`
- `cache_policy`
- `retry_policy`
- `timeout`
- `context_schema`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/func/__init__.py#L262)