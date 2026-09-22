# HostBackendClient

> **Class** in `langgraph_cli`

📖 [View in docs](https://reference.langchain.com/python/langgraph-cli/host_backend/HostBackendClient)

Minimal JSON HTTP client for the host backend deployment service.

## Signature

```python
HostBackendClient(
    self,
    base_url: str,
    api_key: str,
    tenant_id: str | None = None,
)
```

## Constructors

```python
__init__(
    self,
    base_url: str,
    api_key: str,
    tenant_id: str | None = None,
)
```

| Name | Type |
|------|------|
| `base_url` | `str` |
| `api_key` | `str` |
| `tenant_id` | `str \| None` |


## Methods

- [`create_deployment()`](https://reference.langchain.com/python/langgraph-cli/host_backend/HostBackendClient/create_deployment)
- [`list_deployments()`](https://reference.langchain.com/python/langgraph-cli/host_backend/HostBackendClient/list_deployments)
- [`get_deployment()`](https://reference.langchain.com/python/langgraph-cli/host_backend/HostBackendClient/get_deployment)
- [`delete_deployment()`](https://reference.langchain.com/python/langgraph-cli/host_backend/HostBackendClient/delete_deployment)
- [`request_push_token()`](https://reference.langchain.com/python/langgraph-cli/host_backend/HostBackendClient/request_push_token)
- [`request_upload_url()`](https://reference.langchain.com/python/langgraph-cli/host_backend/HostBackendClient/request_upload_url)
- [`update_deployment()`](https://reference.langchain.com/python/langgraph-cli/host_backend/HostBackendClient/update_deployment)
- [`update_deployment_internal_source()`](https://reference.langchain.com/python/langgraph-cli/host_backend/HostBackendClient/update_deployment_internal_source)
- [`list_revisions()`](https://reference.langchain.com/python/langgraph-cli/host_backend/HostBackendClient/list_revisions)
- [`get_revision()`](https://reference.langchain.com/python/langgraph-cli/host_backend/HostBackendClient/get_revision)
- [`get_build_logs()`](https://reference.langchain.com/python/langgraph-cli/host_backend/HostBackendClient/get_build_logs)
- [`get_deploy_logs()`](https://reference.langchain.com/python/langgraph-cli/host_backend/HostBackendClient/get_deploy_logs)

---

[View source on GitHub](https://github.com/langchain-ai/langgraph/blob/1a9baae9592e0c21336f6e09c891ba75481fd657/libs/cli/langgraph_cli/host_backend.py#L19)