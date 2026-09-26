"""Celery/Redis 集成测试：默认跳过，仅 RUN_CELERY_INTEGRATION=1 时运行。

需要可用的 Redis（DB=CELERY_REDIS_DB）与 Celery worker（队列 finance.quant）。
"""

from __future__ import annotations

import os
import time

import pytest

pytestmark = [
    pytest.mark.celery_integration,
    pytest.mark.skipif(
        os.getenv("RUN_CELERY_INTEGRATION", "").strip().lower() not in {"1", "true", "yes", "on"},
        reason="Celery 集成测试默认跳过；设置 RUN_CELERY_INTEGRATION=1 且启动 worker 后运行",
    ),
]


def test_celery_quant_task_round_trip():
    from finance_agent.infrastructure.jobs.celery_app import celery_app
    from finance_agent.infrastructure.jobs.quant_tasks import run_quant_task_celery

    async_result = run_quant_task_celery.apply_async(
        args=[
            "technical_indicators",
            {"high": [1.0, 2.0, 3.0], "low": [0.5, 1.5, 2.5], "close": [1.0, 2.0, 3.0]},
        ],
        queue=celery_app.conf.task_default_queue,
    )
    result = async_result.get(timeout=60)
    assert result["result"]["indicators"]
