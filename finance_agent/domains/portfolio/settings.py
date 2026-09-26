"""Portfolio-domain policy values sourced from environment configuration."""

import os
from dotenv import dotenv_values

_DOTENV_VALUES = dotenv_values()


def _domain_env(name: str, default: str) -> str:
    """Read OS values first, then .env without mutating process-wide settings."""
    if name in os.environ:
        return os.environ[name]
    value = _DOTENV_VALUES.get(name)
    return default if value is None else value

# Preserve historical defaults and environment variable behavior.
PORTFOLIO_MAX_DEPOSIT_AMOUNT = float(_domain_env("PORTFOLIO_MAX_DEPOSIT_AMOUNT", "10000000"))
PORTFOLIO_MIN_ORDER_AMOUNT = float(_domain_env("PORTFOLIO_MIN_ORDER_AMOUNT", "100"))
ALLOCATION_RISK_FREE_RATE = float(_domain_env("ALLOCATION_RISK_FREE_RATE", "0.02"))
ALLOCATION_WEIGHT_MIN = float(_domain_env("ALLOCATION_WEIGHT_MIN", "0.05"))
ALLOCATION_WEIGHT_MAX = float(_domain_env("ALLOCATION_WEIGHT_MAX", "0.60"))
