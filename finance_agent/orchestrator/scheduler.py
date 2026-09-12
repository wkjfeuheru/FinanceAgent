"""任务级重试、超时与依赖调度。"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import ValidationError

from finance_agent.contracts import ExpertResult, ExpertStatus, Task, TaskStatus


@dataclass
class TaskContext:
    """一次任务调用的最小上下文；不携带完整会话历史。"""

    payload: dict[str, Any] = field(default_factory=dict)
    runner: Callable[[Task, dict[str, Any]], Any] | None = None


def _failure(task: Task, *, status: ExpertStatus, error_code: str, summary: str) -> ExpertResult:
    return ExpertResult(
        task_id=task.task_id,
        intent=task.intent,
        expert_name=task.expert_name,
        status=status,
        summary=summary,
        error_code=error_code,
    )


def _validate_result(raw: Any, task: Task) -> ExpertResult:
    if isinstance(raw, ExpertResult):
        result = raw
    elif isinstance(raw, dict):
        required = {"task_id", "intent", "expert_name", "status", "summary"}
        missing = sorted(required - set(raw))
        if missing:
            raise ValidationError.from_exception_data(
                "ExpertResult",
                [{"type": "missing", "loc": (field,), "input": raw} for field in missing],
            )
        result = ExpertResult.model_validate(raw)
    else:
        raise TypeError("专家结果必须是 ExpertResult 或 dict")
    if result.task_id != task.task_id or result.expert_name != task.expert_name:
        raise ValueError("专家结果 task_id 或 expert_name 与任务不匹配")
    return result


def execute_task_with_retry(
    task: Task,
    context: TaskContext,
    *,
    max_retries: int = 2,
    timeout_seconds: float,
    deadline_seconds: float,
) -> ExpertResult:
    """执行任务，所有错误最多初次调用加 max_retries 次重试。"""
    if context.runner is None:
        return _failure(task, status=ExpertStatus.FAILED, error_code="missing_runner", summary="任务没有可执行的专家")
    started = time.monotonic()
    last_error = "unknown"
    payload = dict(context.payload)
    attempts = max(0, int(max_retries)) + 1
    for attempt in range(attempts):
        remaining = float(deadline_seconds) - (time.monotonic() - started)
        if remaining <= 0:
            return _failure(task, status=ExpertStatus.TIMEOUT, error_code="task_deadline", summary="任务超过总超时时间")
        timeout = max(0.001, min(float(timeout_seconds), remaining))
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            future = pool.submit(context.runner, task, payload)
            raw = future.result(timeout=timeout)
            return _validate_result(raw, task)
        except FutureTimeout:
            last_error = "task_timeout"
        except ValidationError as exc:
            last_error = "schema_validation"
            payload = {
                **context.payload,
                "validation_error": {
                    "type": "schema_validation",
                    "invalid_fields": [".".join(str(part) for part in error["loc"]) for error in exc.errors()],
                    "message": "专家结果不符合契约",
                },
            }
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc) or "task_error"
        finally:
            # timeout 后不等待失控的专家线程；Python 线程本身不能被强制杀死，
            # 但 future 已取消，任务生命周期由 deadline 控制。
            pool.shutdown(wait=False, cancel_futures=True)
        if time.monotonic() - started >= float(deadline_seconds):
            return _failure(task, status=ExpertStatus.TIMEOUT, error_code="task_deadline", summary="任务超过总超时时间")
    status = ExpertStatus.TIMEOUT if last_error == "task_timeout" else ExpertStatus.FAILED
    return _failure(task, status=status, error_code=last_error, summary="任务执行失败：" + last_error)


def run_task_dag(
    tasks: list[Task],
    context: TaskContext,
    *,
    max_retries: int = 2,
    timeout_seconds: float,
    deadline_seconds: float,
    initial_results: dict[str, ExpertResult] | None = None,
) -> dict[str, ExpertResult]:
    """按依赖层执行任务；当前层的独立任务并行执行。

    ``initial_results`` 允许把已完成的（例如逐标的扇出聚合出的）结果作为
    依赖满足条件注入，使下游任务不会误判为依赖缺失。
    """
    results: dict[str, ExpertResult] = dict(initial_results or {})
    pending = {task.task_id: task for task in tasks if task.task_id not in results}
    while pending:
        blocked = [
            task for task in pending.values()
            if any(dep in results and results[dep].status is not ExpertStatus.SUCCESS for dep in task.depends_on)
        ]
        for task in blocked:
            results[task.task_id] = _failure(
                task, status=ExpertStatus.FAILED, error_code="dependency_blocked", summary="依赖任务未成功完成",
            )
            pending.pop(task.task_id, None)
        ready = [
            task for task in pending.values()
            if all(dep in results for dep in task.depends_on)
        ]
        if not ready:
            for task in pending.values():
                results[task.task_id] = _failure(
                    task, status=ExpertStatus.FAILED, error_code="dependency_cycle", summary="任务依赖存在循环",
                )
            break
        with ThreadPoolExecutor(max_workers=len(ready)) as pool:
            futures = {
                task.task_id: pool.submit(
                    execute_task_with_retry,
                    task,
                    TaskContext(
                        payload={
                            **context.payload,
                            "upstream_results": {
                                dependency: results[dependency].model_dump(mode="json")
                                for dependency in task.depends_on
                            },
                        },
                        runner=context.runner,
                    ),
                    max_retries=max_retries,
                    timeout_seconds=timeout_seconds,
                    deadline_seconds=deadline_seconds,
                )
                for task in ready
            }
            for task in ready:
                results[task.task_id] = futures[task.task_id].result()
                pending.pop(task.task_id, None)
    return results


__all__ = ["TaskContext", "execute_task_with_retry", "run_task_dag"]
