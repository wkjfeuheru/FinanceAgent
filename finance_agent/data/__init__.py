"""Data infrastructure layer: unified provider manager and stores."""

from finance_agent.data.auth import get_user_store
from finance_agent.data.product_library import get_product_library
from finance_agent.data.provider_manager import (
    ProviderManager,
    get_provider_manager,
)
from finance_agent.data.providers import (
    ProviderError,
    ProviderUnavailableError,
    UnsupportedProviderCapability,
)

__all__ = [
    # 统一 Provider 路由
    "ProviderManager",
    "get_provider_manager",
    "ProviderError",
    "ProviderUnavailableError",
    "UnsupportedProviderCapability",
    # 存储
    "get_product_library",
    "get_user_store",
]
