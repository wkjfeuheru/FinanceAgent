"""Guard API/frontend structure and shared transports.

Backend route modules must not reach into one another's private names; shared
dependency/auth helpers live in ``api.dependencies``. The frontend must expose a
single authenticated HTTP client instead of one Axios instance per API module.
"""

from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
API_DIR = REPO_ROOT / "finance_agent" / "api"
FRONTEND_API_DIR = REPO_ROOT / "frontend" / "src" / "api"

_ROUTE_MODULES = ("auth.py", "chat.py", "conversations.py", "health.py", "admin.py", "portfolio.py")
_API_GROUPS = ("auth", "chat", "conversations", "health", "portfolio", "admin")
#: 这些路由的 handler 全部是「同步 DB/服务调用」，必须保持同步 ``def``，
#: 由 Starlette 放进线程池执行；写成 ``async def`` 会让阻塞调用直接跑在事件循环上。
_SYNC_ONLY_ROUTE_MODULES = ("portfolio.py", "admin.py", "health.py")


def test_api_layout_matches_target_tree() -> None:
    """API 实现应落在明确的 routers/schemas 包，而非 api 根目录平铺。"""
    required = [
        API_DIR / "routers" / f"{group}.py" for group in _API_GROUPS
    ] + [
        API_DIR / "schemas" / f"{group}.py" for group in _API_GROUPS
    ] + [API_DIR / "app.py"]
    missing = [str(path.relative_to(REPO_ROOT)) for path in required if not path.is_file()]
    assert missing == [], "missing target API modules: " + ", ".join(missing)

    legacy = [
        API_DIR / f"{group}_{suffix}.py"
        for group in _API_GROUPS
        for suffix in ("routes", "schemas")
    ] + [API_DIR / "routes.py", API_DIR / "schemas.py"]
    stale = [str(path.relative_to(REPO_ROOT)) for path in legacy if path.exists()]
    assert stale == [], "legacy flat API modules remain: " + ", ".join(stale)


def test_route_modules_do_not_import_other_routers_private_names() -> None:
    """路由模块之间不得互相导入下划线私有名（共享入口是 api.dependencies）。"""
    offenders: list[str] = []
    for name in _ROUTE_MODULES:
        path = API_DIR / "routers" / name
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if not node.module.startswith("finance_agent.api."):
                continue
            source = node.module.rsplit(".", 1)[-1]
            if source not in {Path(item).stem for item in _ROUTE_MODULES}:
                continue
            if source == path.stem:
                continue
            for alias in node.names:
                if alias.name.startswith("_"):
                    offenders.append(f"{name} imports {node.module}.{alias.name}")
    assert offenders == [], "Routers must share via api.dependencies:\n" + "\n".join(offenders)


def test_router_modules_use_the_shared_dependencies_module() -> None:
    """路由共享认证与依赖逻辑应由 api.dependencies 提供。"""
    for group in _API_GROUPS:
        path = API_DIR / "routers" / f"{group}.py"
        if group in {"admin", "auth", "chat", "conversations", "health", "portfolio"}:
            assert path.is_file()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert "finance_agent.api.dependencies" in imports, (
            f"{path.name} must use api.dependencies as its shared dependency entry"
        )


def test_main_api_paths_and_sse_response_remain_compatible(monkeypatch) -> None:
    """分组注册后所有旧 REST 路径仍在，SSE 运行时仍返回 text/event-stream。"""
    import asyncio

    from finance_agent.main import app
    from finance_agent.api.app import app as assembled_app
    from finance_agent.api.routers import chat
    from finance_agent.api.schemas.chat import ChatRequest

    schema = app.openapi()
    assert app is assembled_app
    api_paths = {path for path in schema["paths"] if path.startswith("/api/")}
    expected_paths = {
        "/api/register", "/api/login", "/api/logout", "/api/me", "/api/account",
        "/api/chat", "/api/chat/stream", "/api/chat/stop", "/api/runs/{task_id}",
        "/api/profile/{customer_id}", "/api/history/{customer_id}",
        "/api/conversations/{customer_id}",
        "/api/conversations/{customer_id}/{conversation_id}",
        "/api/conversations/{customer_id}/{conversation_id}/messages", "/api/reset/{customer_id}",
        "/api/health", "/api/health/degradation", "/api/admin/clear-records",
        "/api/admin/users", "/api/admin/users/{customer_id}/portfolio", "/api/admin/products",
        "/api/admin/products/{code}/offline", "/api/admin/products/{code}/publish",
        "/api/portfolio/products", "/api/portfolio/products/{code}", "/api/portfolio/account",
        "/api/portfolio/positions", "/api/portfolio/deposit", "/api/portfolio/orders",
        "/api/portfolio/liquidate", "/api/portfolio/transactions",
    }
    assert api_paths == expected_paths

    class _Request:
        headers = {}

    class _System:
        async def handle_message_stream(self, **kwargs):
            yield {"type": "response", "response": "ok"}

    monkeypatch.setattr(chat, "_resolve_customer_id", lambda *args: "CUST1")
    monkeypatch.setattr(chat, "_authorize_conversation", lambda *args: None)
    monkeypatch.setattr(chat, "get_system", lambda: _System())
    response = asyncio.run(chat.chat_stream(ChatRequest(message="hello"), _Request()))
    assert response.headers["content-type"].startswith("text/event-stream")


def test_frontend_uses_a_single_axios_client() -> None:
    """src 中所有 TypeScript/Vue 文件合计只能创建一个 Axios 客户端。"""
    frontend_src = REPO_ROOT / "frontend" / "src"
    sources = sorted((*frontend_src.rglob("*.ts"), *frontend_src.rglob("*.vue")))
    assert sources, "frontend source modules must exist"
    total = 0
    locations: list[str] = []
    for path in sources:
        text = path.read_text(encoding="utf-8")
        count = text.count("axios.create(")
        if count:
            locations.append(f"{path.relative_to(REPO_ROOT)}:{count}")
            total += count
    assert total == 1, (
        "expected exactly one axios.create (shared client); found: " + ", ".join(locations)
    )


def test_frontend_api_and_app_modules_follow_feature_boundaries() -> None:
    """应用状态、共享传输与业务 API 应位于各自的目标目录。"""
    frontend_src = REPO_ROOT / "frontend" / "src"
    required = [
        frontend_src / "app" / "router.ts",
        frontend_src / "app" / "session.ts",
        FRONTEND_API_DIR / "client.ts",
        FRONTEND_API_DIR / "errors.ts",
        FRONTEND_API_DIR / "sse.ts",
        frontend_src / "shared" / "format.ts",
        *(frontend_src / "features" / group / "api.ts"
          for group in ("auth", "chat", "portfolio", "admin")),
    ]
    missing = [str(path.relative_to(REPO_ROOT)) for path in required if not path.is_file()]
    assert missing == [], "missing target frontend modules: " + ", ".join(missing)

    legacy = [
        FRONTEND_API_DIR / f"{group}.ts"
        for group in ("chat", "portfolio", "admin")
    ] + [frontend_src / "router", frontend_src / "utils"]
    stale = [str(path.relative_to(REPO_ROOT)) for path in legacy if path.exists()]
    assert stale == [], "legacy frontend modules remain: " + ", ".join(stale)


def test_blocking_route_handlers_stay_synchronous() -> None:
    """同步 DB/服务实现的路由必须是 ``def``，不得写成 ``async def``。

    事件循环里直接执行阻塞调用时，一次慢查询（或存储层死锁）就会冻住整个 API：
    ``/api/health``、任意新路径乃至新建 TCP 连接都会一起无响应。持仓/账户接口正是
    这样把「商品」页一起拖垮的，因此这条不变式要有测试守着。
    """
    offenders: list[str] = []
    for name in _SYNC_ONLY_ROUTE_MODULES:
        path = API_DIR / "routers" / name
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno} {node.name}")
    assert offenders == [], (
        "阻塞路由必须保持同步 def（交给线程池），不得在事件循环里跑同步 DB 调用:\n"
        + "\n".join(offenders)
    )
