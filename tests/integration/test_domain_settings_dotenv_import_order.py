"""Domain policy settings should honor .env regardless of ASGI import order."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DOMAIN_ENV_NAMES = {
    "PORTFOLIO_MAX_DEPOSIT_AMOUNT",
    "PORTFOLIO_MIN_ORDER_AMOUNT",
    "ALLOCATION_RISK_FREE_RATE",
    "ALLOCATION_WEIGHT_MIN",
    "ALLOCATION_WEIGHT_MAX",
}


def test_asgi_import_loads_domain_policy_values_from_dotenv(work_dir: Path) -> None:
    """Importing the ASGI app first must not freeze domain defaults before .env loads."""
    dotenv_values = {
        "PORTFOLIO_MAX_DEPOSIT_AMOUNT": "7654321.5",
        "PORTFOLIO_MIN_ORDER_AMOUNT": "17.25",
        "ALLOCATION_RISK_FREE_RATE": "0.031",
        "ALLOCATION_WEIGHT_MIN": "0.11",
        "ALLOCATION_WEIGHT_MAX": "0.72",
    }
    (work_dir / ".env").write_text(
        "\n".join(f"{name}={value}" for name, value in dotenv_values.items()),
        encoding="utf-8",
    )

    child_env = {
        name: value
        for name, value in os.environ.items()
        if name not in DOMAIN_ENV_NAMES
    }
    child_env.update({
        "DEEPSEEK_API_KEY": "test-key",
        "PYTHONPATH": str(REPO_ROOT),
    })
    script = """
import json
import finance_agent.api.app
from finance_agent.domains.portfolio import settings
print(json.dumps({
    "PORTFOLIO_MAX_DEPOSIT_AMOUNT": settings.PORTFOLIO_MAX_DEPOSIT_AMOUNT,
    "PORTFOLIO_MIN_ORDER_AMOUNT": settings.PORTFOLIO_MIN_ORDER_AMOUNT,
    "ALLOCATION_RISK_FREE_RATE": settings.ALLOCATION_RISK_FREE_RATE,
    "ALLOCATION_WEIGHT_MIN": settings.ALLOCATION_WEIGHT_MIN,
    "ALLOCATION_WEIGHT_MAX": settings.ALLOCATION_WEIGHT_MAX,
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=work_dir,
        env=child_env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1]) == {
        name: float(value) for name, value in dotenv_values.items()
    }
