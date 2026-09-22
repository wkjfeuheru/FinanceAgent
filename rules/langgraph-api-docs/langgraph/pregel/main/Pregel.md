# Pregel

> **Class** in `langgraph`

📖 [View in docs](https://reference.langchain.com/python/langgraph/pregel/main/Pregel)

Pregel manages the runtime behavior for LangGraph applications.

## Overview

Pregel combines [**actors**](https://en.wikipedia.org/wiki/Actor_model)
and **channels** into a single application.
**Actors** read data from channels and write data to channels.
Pregel organizes the execution of the application into multiple steps,
following the **Pregel Algorithm**/**Bulk Synchronous Parallel** model.

Each step consists of three phases:

- **Plan**: Determine which **actors** to execute in this step. For example,
    in the first step, select the **actors** that subscribe to the special
    **input** channels; in subsequent steps,
    select the **actors** that subscribe to channels updated in the previous step.
- **Execution**: Execute all selected **actors** in parallel,
    until all complete, or one fails, or a timeout is reached. During this
    phase, channel updates are invisible to actors until the next step.
- **Update**: Update the channels with the values written by the **actors**
    in this step.

Repeat until no **actors** are selected for execution, or a maximum number of
steps is reached.

## Actors

An **actor** is a `PregelNode`.
It subscribes to channels, reads data from them, and writes data to them.
It can be thought of as an **actor** in the Pregel algorithm.
`PregelNodes` implement LangChain's
Runnable interface.

## Channels

Channels are used to communicate between actors (`PregelNodes`).
Each channel has a value type, an update type, and an update function – which
takes a sequence of updates and
modifies the stored value. Channels can be used to send data from one chain to
another, or to send data from a chain to itself in a future step. LangGraph
provides a number of built-in channels:

### Basic channels: LastValue and Topic

- `LastValue`: The default channel, stores the last value sent to the channel,
   useful for input and output values, or for sending data from one step to the next
- `Topic`: A configurable PubSub Topic, useful for sending multiple values
   between *actors*, or for accumulating output. Can be configured to deduplicate
   values, and/or to accumulate values over the course of multiple steps.

### Advanced channels: Context and BinaryOperatorAggregate

- `Context`: exposes the value of a context manager, managing its lifecycle.
    Useful for accessing external resources that require setup and/or teardown. e.g.
    `client = Context(httpx.Client)`
- `BinaryOperatorAggregate`: stores a persistent value, updated by applying
    a binary operator to the current value and each update
    sent to the channel, useful for computing aggregates over multiple steps. e.g.
    `total = BinaryOperatorAggregate(int, operator.add)`

## Examples

Most users will interact with Pregel via a
[StateGraph (Graph API)][langgraph.graph.StateGraph] or via an
[entrypoint (Functional API)][langgraph.func.entrypoint].

However, for **advanced** use cases, Pregel can be used directly. If you're
not sure whether you need to use Pregel directly, then the answer is probably no
- you should use the Graph API or Functional API instead. These are higher-level
interfaces that will compile down to Pregel under the hood.

Here are some examples to give you a sense of how it works:

## Signature

```python
Pregel(
    self,
    *,
    nodes: dict[str, PregelNode | NodeBuilder],
    channels: dict[str, BaseChannel | ManagedValueSpec] | None,
    auto_validate: bool = True,
    stream_mode: StreamMode = 'values',
    stream_eager: bool = False,
    output_channels: str | Sequence[str],
    stream_channels: str | Sequence[str] | None = None,
    interrupt_after_nodes: All | Sequence[str] = (),
    interrupt_before_nodes: All | Sequence[str] = (),
    input_channels: str | Sequence[str],
    step_timeout: float | None = None,
    debug: bool | None = None,
    checkpointer: Checkpointer = None,
    store: BaseStore | None = None,
    cache: BaseCache | None = None,
    retry_policy: RetryPolicy | Sequence[RetryPolicy] = (),
    cache_policy: CachePolicy | None = None,
    context_schema: type[ContextT] | None = None,
    config: RunnableConfig | None = None,
    trigger_to_nodes: Mapping[str, Sequence[str]] | None = None,
    node_error_handler_map: Mapping[str, str] | None = None,
    name: str = 'LangGraph',
    stream_transformers: Sequence[Callable[[tuple[str, ...]], Any]] | None = None,
    **deprecated_kwargs: Unpack[DeprecatedKwargs] = {},
)
```

## Description

**Single node application:**

```python
from langgraph.channels import EphemeralValue
from langgraph.pregel import Pregel, NodeBuilder

node1 = (
    NodeBuilder().subscribe_only("a")
    .do(lambda x: x + x)
    .write_to("b")
)

app = Pregel(
    nodes={"node1": node1},
    channels={
        "a": EphemeralValue(str),
        "b": EphemeralValue(str),
    },
    input_channels=["a"],
    output_channels=["b"],
)

app.invoke({"a": "foo"})
```

```con
{'b': 'foofoo'}
```

**Using multiple nodes and multiple output channels:**

```python
from langgraph.channels import LastValue, EphemeralValue
from langgraph.pregel import Pregel, NodeBuilder

node1 = (
    NodeBuilder().subscribe_only("a")
    .do(lambda x: x + x)
    .write_to("b")
)

node2 = (
    NodeBuilder().subscribe_to("b")
    .do(lambda x: x["b"] + x["b"])
    .write_to("c")
)

app = Pregel(
    nodes={"node1": node1, "node2": node2},
    channels={
        "a": EphemeralValue(str),
        "b": LastValue(str),
        "c": EphemeralValue(str),
    },
    input_channels=["a"],
    output_channels=["b", "c"],
)

app.invoke({"a": "foo"})
```

```con
{'b': 'foofoo', 'c': 'foofoofoofoo'}
```

**Using a Topic channel:**

```python
from langgraph.channels import LastValue, EphemeralValue, Topic
from langgraph.pregel import Pregel, NodeBuilder

node1 = (
    NodeBuilder().subscribe_only("a")
    .do(lambda x: x + x)
    .write_to("b", "c")
)

node2 = (
    NodeBuilder().subscribe_only("b")
    .do(lambda x: x + x)
    .write_to("c")
)

app = Pregel(
    nodes={"node1": node1, "node2": node2},
    channels={
        "a": EphemeralValue(str),
        "b": EphemeralValue(str),
        "c": Topic(str, accumulate=True),
    },
    input_channels=["a"],
    output_channels=["c"],
)

app.invoke({"a": "foo"})
```

```pycon
{"c": ["foofoo", "foofoofoofoo"]}
```

**Using a `BinaryOperatorAggregate` channel:**

```python
from langgraph.channels import EphemeralValue, BinaryOperatorAggregate
from langgraph.pregel import Pregel, NodeBuilder

node1 = (
    NodeBuilder().subscribe_only("a")
    .do(lambda x: x + x)
    .write_to("b", "c")
)

node2 = (
    NodeBuilder().subscribe_only("b")
    .do(lambda x: x + x)
    .write_to("c")
)

def reducer(current, update):
    if current:
        return current + " | " + update
    else:
        return update

app = Pregel(
    nodes={"node1": node1, "node2": node2},
    channels={
        "a": EphemeralValue(str),
        "b": EphemeralValue(str),
        "c": BinaryOperatorAggregate(str, operator=reducer),
    },
    input_channels=["a"],
    output_channels=["c"],
)

app.invoke({"a": "foo"})
```

```con
{'c': 'foofoo | foofoofoofoo'}
```

**Introducing a cycle:**

This example demonstrates how to introduce a cycle in the graph, by having
a chain write to a channel it subscribes to.

Execution will continue until a `None` value is written to the channel.

```python
from langgraph.channels import EphemeralValue
from langgraph.pregel import Pregel, NodeBuilder, ChannelWriteEntry

example_node = (
    NodeBuilder()
    .subscribe_only("value")
    .do(lambda x: x + x if len(x) < 10 else None)
    .write_to(ChannelWriteEntry(channel="value", skip_none=True))
)

app = Pregel(
    nodes={"example_node": example_node},
    channels={
        "value": EphemeralValue(str),
    },
    input_channels=["value"],
    output_channels=["value"],
)

app.invoke({"value": "a"})
```

```con
{'value': 'aaaaaaaaaaaaaaaa'}
```

## Extends

- `PregelProtocol[StateT, ContextT, InputT, OutputT]`
- `Generic[StateT, ContextT, InputT, OutputT]`

## Constructors

```python
__init__(
    self,
    *,
    nodes: dict[str, PregelNode | NodeBuilder],
    channels: dict[str, BaseChannel | ManagedValueSpec] | None,
    auto_validate: bool = True,
    stream_mode: StreamMode = 'values',
    stream_eager: bool = False,
    output_channels: str | Sequence[str],
    stream_channels: str | Sequence[str] | None = None,
    interrupt_after_nodes: All | Sequence[str] = (),
    interrupt_before_nodes: All | Sequence[str] = (),
    input_channels: str | Sequence[str],
    step_timeout: float | None = None,
    debug: bool | None = None,
    checkpointer: Checkpointer = None,
    store: BaseStore | None = None,
    cache: BaseCache | None = None,
    retry_policy: RetryPolicy | Sequence[RetryPolicy] = (),
    cache_policy: CachePolicy | None = None,
    context_schema: type[ContextT] | None = None,
    config: RunnableConfig | None = None,
    trigger_to_nodes: Mapping[str, Sequence[str]] | None = None,
    node_error_handler_map: Mapping[str, str] | None = None,
    name: str = 'LangGraph',
    stream_transformers: Sequence[Callable[[tuple[str, ...]], Any]] | None = None,
    **deprecated_kwargs: Unpack[DeprecatedKwargs] = {},
) -> None
```

| Name | Type |
|------|------|
| `nodes` | `dict[str, PregelNode \| NodeBuilder]` |
| `channels` | `dict[str, BaseChannel \| ManagedValueSpec] \| None` |
| `auto_validate` | `bool` |
| `stream_mode` | `StreamMode` |
| `stream_eager` | `bool` |
| `output_channels` | `str \| Sequence[str]` |
| `stream_channels` | `str \| Sequence[str] \| None` |
| `interrupt_after_nodes` | `All \| Sequence[str]` |
| `interrupt_before_nodes` | `All \| Sequence[str]` |
| `input_channels` | `str \| Sequence[str]` |
| `step_timeout` | `float \| None` |
| `debug` | `bool \| None` |
| `checkpointer` | `Checkpointer` |
| `store` | `BaseStore \| None` |
| `cache` | `BaseCache \| None` |
| `retry_policy` | `RetryPolicy \| Sequence[RetryPolicy]` |
| `cache_policy` | `CachePolicy \| None` |
| `context_schema` | `type[ContextT] \| None` |
| `config` | `RunnableConfig \| None` |
| `trigger_to_nodes` | `Mapping[str, Sequence[str]] \| None` |
| `node_error_handler_map` | `Mapping[str, str] \| None` |
| `name` | `str` |
| `stream_transformers` | `Sequence[Callable[[tuple[str, ...]], Any]] \| None` |


## Properties

- `nodes`
- `channels`
- `stream_mode`
- `stream_eager`
- `output_channels`
- `stream_channels`
- `interrupt_after_nodes`
- `interrupt_before_nodes`
- `input_channels`
- `step_timeout`
- `debug`
- `checkpointer`
- `store`
- `cache`
- `retry_policy`
- `cache_policy`
- `context_schema`
- `config`
- `name`
- `trigger_to_nodes`
- `node_error_handler_map`
- `stream_transformers`
- `InputType`
- `OutputType`
- `stream_channels_list`
- `stream_channels_asis`

## Methods

- [`get_graph()`](https://reference.langchain.com/python/langgraph/pregel/main/Pregel/get_graph)
- [`aget_graph()`](https://reference.langchain.com/python/langgraph/pregel/main/Pregel/aget_graph)
- [`copy()`](https://reference.langchain.com/python/langgraph/pregel/main/Pregel/copy)
- [`with_config()`](https://reference.langchain.com/python/langgraph/pregel/main/Pregel/with_config)
- [`validate()`](https://reference.langchain.com/python/langgraph/pregel/main/Pregel/validate)
- [`config_schema()`](https://reference.langchain.com/python/langgraph/pregel/main/Pregel/config_schema)
- [`get_config_jsonschema()`](https://reference.langchain.com/python/langgraph/pregel/main/Pregel/get_config_jsonschema)
- [`get_context_jsonschema()`](https://reference.langchain.com/python/langgraph/pregel/main/Pregel/get_context_jsonschema)
- [`get_input_schema()`](https://reference.langchain.com/python/langgraph/pregel/main/Pregel/get_input_schema)
- [`get_input_jsonschema()`](https://reference.langchain.com/python/langgraph/pregel/main/Pregel/get_input_jsonschema)
- [`get_output_schema()`](https://reference.langchain.com/python/langgraph/pregel/main/Pregel/get_output_schema)
- [`get_output_jsonschema()`](https://reference.langchain.com/python/langgraph/pregel/main/Pregel/get_output_jsonschema)
- [`get_subgraphs()`](https://reference.langchain.com/python/langgraph/pregel/main/Pregel/get_subgraphs)
- [`aget_subgraphs()`](https://reference.langchain.com/python/langgraph/pregel/main/Pregel/aget_subgraphs)
- [`get_state()`](https://reference.langchain.com/python/langgraph/pregel/main/Pregel/get_state)
- [`aget_state()`](https://reference.langchain.com/python/langgraph/pregel/main/Pregel/aget_state)
- [`get_state_history()`](https://reference.langchain.com/python/langgraph/pregel/main/Pregel/get_state_history)
- [`aget_state_history()`](https://reference.langchain.com/python/langgraph/pregel/main/Pregel/aget_state_history)
- [`bulk_update_state()`](https://reference.langchain.com/python/langgraph/pregel/main/Pregel/bulk_update_state)
- [`abulk_update_state()`](https://reference.langchain.com/python/langgraph/pregel/main/Pregel/abulk_update_state)
- [`update_state()`](https://reference.langchain.com/python/langgraph/pregel/main/Pregel/update_state)
- [`aupdate_state()`](https://reference.langchain.com/python/langgraph/pregel/main/Pregel/aupdate_state)
- [`stream()`](https://reference.langchain.com/python/langgraph/pregel/main/Pregel/stream)
- [`astream()`](https://reference.langchain.com/python/langgraph/pregel/main/Pregel/astream)
- [`stream_events()`](https://reference.langchain.com/python/langgraph/pregel/main/Pregel/stream_events)
- [`astream_events()`](https://reference.langchain.com/python/langgraph/pregel/main/Pregel/astream_events)
- [`invoke()`](https://reference.langchain.com/python/langgraph/pregel/main/Pregel/invoke)
- [`ainvoke()`](https://reference.langchain.com/python/langgraph/pregel/main/Pregel/ainvoke)
- [`clear_cache()`](https://reference.langchain.com/python/langgraph/pregel/main/Pregel/clear_cache)
- [`aclear_cache()`](https://reference.langchain.com/python/langgraph/pregel/main/Pregel/aclear_cache)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/23652c54be18ce59f697aa38f10075ee91913220/libs/langgraph/langgraph/pregel/main.py#L449)