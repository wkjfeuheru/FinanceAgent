"""Celery 应用：量化计算使用独立 Redis DB 与专用队列（设计 §11）。"""

from __future__ import annotations

from celery import Celery

from finance_agent import config


def _broker_url() -> str:
    """在既有 Redis 上切换到独立的 Celery DB。"""
    base = config.REDIS_URL.rsplit("/", 1)[0]
    return f"{base}/{config.CELERY_REDIS_DB}"


def build_celery_app() -> Celery:
    app = Celery(
        "finance_agent",
        broker=_broker_url(),
        backend=_broker_url(),
        include=["finance_agent.tasks.quant"],
    )
    app.conf.update(
        task_default_queue=config.CELERY_QUANT_QUEUE,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        task_soft_time_limit=config.CELERY_TASK_SOFT_TIME_LIMIT,
        task_time_limit=config.CELERY_TASK_HARD_TIME_LIMIT,
        result_expires=config.CELERY_RESULT_EXPIRES,
        broker_transport_options={"visibility_timeout": config.CELERY_TASK_HARD_TIME_LIMIT},
        task_default_priority=5,
    )
    return app


celery_app = build_celery_app()
