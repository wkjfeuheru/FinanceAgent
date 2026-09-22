# Config

> **Class** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/schemas/Config)

Top-level config for langgraph-cli or similar deployment tooling.

## Signature

```python
Config()
```

## Extends

- `TypedDict`

## Constructors

```python
__init__(
    python_version: str,
    node_version: str | None,
    api_version: str | None,
    base_image: str | None,
    image_distro: Distros | None,
    pip_config_file: str | None,
    pip_installer: str | None,
    source: UvSource | None,
    dockerfile_lines: list[str],
    dependencies: list[str],
    graphs: dict[str, str | GraphDef],
    env: dict[str, str] | str,
    store: StoreConfig | None,
    checkpointer: CheckpointerConfig | None,
    auth: AuthConfig | None,
    encryption: EncryptionConfig | None,
    http: HttpConfig | None,
    webhooks: WebhooksConfig | None,
    ui: dict[str, str] | None,
    keep_pkg_tools: bool | list[str] | None,
)
```

| Name | Type |
|------|------|
| `python_version` | `str` |
| `node_version` | `str \| None` |
| `api_version` | `str \| None` |
| `base_image` | `str \| None` |
| `image_distro` | `Distros \| None` |
| `pip_config_file` | `str \| None` |
| `pip_installer` | `str \| None` |
| `source` | `UvSource \| None` |
| `dockerfile_lines` | `list[str]` |
| `dependencies` | `list[str]` |
| `graphs` | `dict[str, str \| GraphDef]` |
| `env` | `dict[str, str] \| str` |
| `store` | `StoreConfig \| None` |
| `checkpointer` | `CheckpointerConfig \| None` |
| `auth` | `AuthConfig \| None` |
| `encryption` | `EncryptionConfig \| None` |
| `http` | `HttpConfig \| None` |
| `webhooks` | `WebhooksConfig \| None` |
| `ui` | `dict[str, str] \| None` |
| `keep_pkg_tools` | `bool \| list[str] \| None` |


## Properties

- `python_version`
- `node_version`
- `api_version`
- `base_image`
- `image_distro`
- `pip_config_file`
- `pip_installer`
- `source`
- `dockerfile_lines`
- `dependencies`
- `graphs`
- `env`
- `store`
- `checkpointer`
- `auth`
- `encryption`
- `http`
- `webhooks`
- `ui`
- `keep_pkg_tools`

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/schemas.py#L615)