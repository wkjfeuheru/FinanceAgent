"""API 共享依赖与鉴权门禁（Task 5）。

此前这些依赖散在 ``api/routes.py``，``admin_routes`` / ``portfolio_routes`` 直接
从**另一个路由模块**导入私有函数（``routes._require_admin`` /
``routes._require_customer_id``），形成 router↔router 私有耦合。现在它们只依赖本
模块：``dependencies`` 是路由层唯一共享的依赖/鉴权入口，不反向依赖任何路由模块。

路由模块直接复用这里的共享依赖，不再通过聚合路由模块转发。
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request

from finance_agent.infrastructure.settings import ADMIN_CUSTOMER_IDS
from finance_agent.infrastructure.persistence.postgres.registry import get_user_store
from finance_agent.application.advisor import AdvisorSystem

# 全局系统实例（延迟初始化）
_system: AdvisorSystem | None = None


def get_system() -> AdvisorSystem:
    """获取或初始化投顾系统实例。"""
    global _system
    if _system is None:
        _system = AdvisorSystem()
    return _system


def resolve_customer_id(request: Request) -> str:
    """从 Authorization: Bearer 解析并校验 token，返回 customer_id；失败抛 401。"""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    customer_id = get_user_store().verify_token(auth_header[7:].strip())
    if not customer_id:
        raise HTTPException(status_code=401, detail="令牌无效或已过期")
    return customer_id


#: 旧名兼容（测试与既有调用方使用下划线前缀）。
_require_customer_id = resolve_customer_id


def resolve_chat_customer_id(
    http_request: Request, request: Any = None, x_customer_id: str | None = None,
) -> str:
    """对话接口的 customer_id 解析：始终要求有效 Bearer token。

    签名保留 ``request`` / ``x_customer_id`` 以兼容既有调用点与测试；匿名模式
    已关闭，因此二者不再参与解析。
    """
    return _require_customer_id(http_request)


_resolve_customer_id = resolve_chat_customer_id


def authorize_customer(request: Request, path_customer_id: str) -> str:
    """要求已登录，且路径中的 customer_id 必须等于登录用户，否则 403。"""
    current = _require_customer_id(request)
    if str(current).upper() != str(path_customer_id).upper():
        raise HTTPException(status_code=403, detail="无权访问该客户资源")
    return current


_authorize_customer = authorize_customer


def authorize_conversation(customer_id: str, conversation_id: str) -> None:
    """校验会话归属；非本人会话一律 404，避免跨用户读写。

    空 conversation_id 表示新建会话，不做校验。
    """
    if not conversation_id:
        return
    from finance_agent.orchestration.persistence_database import get_database

    if get_database().get_conversation(conversation_id, customer_id) is None:
        raise HTTPException(status_code=404, detail="对话不存在")


_authorize_conversation = authorize_conversation


def is_admin(customer_id: str) -> bool:
    """判断客户是否为管理员。

    两条路径取并集：命中 ``ADMIN_CUSTOMER_IDS`` 环境变量白名单，或库内
    ``finance.users.is_admin`` 为真。白名单保留是为了让"改配置即可授权"的既有
    运维方式继续可用；库内角色则是可持久、可在后台自助授予的正式路径。

    角色查询失败必须**失败关闭**：宁可把管理员操作拒掉，也不能因为库不可用
    就让任何人都成为管理员。
    """
    if str(customer_id).upper() in ADMIN_CUSTOMER_IDS:
        return True
    checker = getattr(get_user_store(), "is_admin", None)
    if checker is None:
        return False
    try:
        return bool(checker(customer_id))
    except Exception:  # noqa: BLE001 - 授权查询失败按"非管理员"处理
        return False


_is_admin = is_admin


def require_admin(request: Request) -> str:
    customer_id = _require_customer_id(request)
    if not _is_admin(customer_id):
        raise HTTPException(status_code=403, detail="仅管理员可访问该接口")
    return customer_id


_require_admin = require_admin


__all__ = [
    "ADMIN_CUSTOMER_IDS",
    "_authorize_conversation",
    "_authorize_customer",
    "_is_admin",
    "_require_admin",
    "_require_customer_id",
    "_resolve_customer_id",
    "authorize_conversation",
    "authorize_customer",
    "get_system",
    "get_user_store",
    "is_admin",
    "require_admin",
    "resolve_chat_customer_id",
    "resolve_customer_id",
]
