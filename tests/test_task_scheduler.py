"""任务级重试、超时和依赖调度测试。"""

import time

from finance_agent.contracts import ExpertStatus, IntentKind, Task, TaskStatus
from finance_agent.orchestrator.scheduler import (
    TaskContext,
    execute_task_with_retry,
    run_task_dag,
)


def _task(task_id="task-1", depends_on=None):
    return Task(
        task_id=task_id,
        intent=IntentKind.STOCK_ANALYSIS,
        expert_name="stock_analysis",
        requirement="分析600519",
        execution_mode="stock_analysis",
        depends_on=list(depends_on or []),
    )


def test_task_execution_retries_errors_and_returns_success():
    attempts = []

    def runner(task, payload):
        attempts.append(payload)
        if len(attempts) < 3:
            raise RuntimeError("temporary")
        return {
            "task_id": task.task_id,
            "intent": task.intent.value,
            "expert_name": task.expert_name,
            "status": "success",
            "summary": "完成",
        }

    result = execute_task_with_retry(
        _task(),
        TaskContext(payload={"message": "分析600519"}, runner=runner),
        max_retries=2,
        timeout_seconds=1,
        deadline_seconds=5,
    )

    assert result.status is ExpertStatus.SUCCESS
    assert len(attempts) == 3


def test_task_execution_retries_protocol_error_with_field_feedback():
    payloads = []

    def runner(task, payload):
        payloads.append(payload)
        if len(payloads) == 1:
            return {"task_id": task.task_id, "status": "success"}
        return {
            "task_id": task.task_id,
            "intent": task.intent.value,
            "expert_name": task.expert_name,
            "status": "success",
            "summary": "修复后完成",
        }

    result = execute_task_with_retry(
        _task(),
        TaskContext(payload={}, runner=runner),
        max_retries=2,
        timeout_seconds=1,
        deadline_seconds=5,
    )

    assert result.status is ExpertStatus.SUCCESS
    assert payloads[1]["validation_error"]["type"] == "schema_validation"


def test_task_dag_blocks_dependents_when_dependency_fails():
    calls = []

    def runner(task, payload):
        calls.append(task.task_id)
        if task.task_id == "task-1":
            raise RuntimeError("source down")
        return {
            "task_id": task.task_id,
            "intent": task.intent.value,
            "expert_name": task.expert_name,
            "status": "success",
            "summary": "完成",
        }

    results = run_task_dag(
        [_task("task-1"), _task("task-2", ["task-1"])],
        TaskContext(payload={}, runner=runner),
        max_retries=0,
        timeout_seconds=1,
        deadline_seconds=5,
    )

    assert results["task-1"].status is ExpertStatus.FAILED
    assert results["task-2"].status is ExpertStatus.FAILED
    assert results["task-2"].error_code == "dependency_blocked"
    assert calls == ["task-1"]


def test_task_dag_passes_successful_dependency_results_to_downstream_task():
    received = []

    def runner(task, payload):
        received.append((task.task_id, payload))
        return {
            "task_id": task.task_id,
            "intent": task.intent.value,
            "expert_name": task.expert_name,
            "status": "success",
            "summary": "完成",
            "result_data": {"value": task.task_id},
        }

    results = run_task_dag(
        [_task("task-1"), _task("task-2", ["task-1"])],
        TaskContext(payload={}, runner=runner),
        max_retries=0,
        timeout_seconds=1,
        deadline_seconds=5,
    )

    assert results["task-2"].status is ExpertStatus.SUCCESS
    assert received[1][1]["upstream_results"]["task-1"]["result_data"] == {"value": "task-1"}


def test_task_execution_timeout_does_not_wait_for_stuck_runner():
    started = time.monotonic()

    def runner(task, payload):
        time.sleep(0.25)
        return {
            "task_id": task.task_id,
            "intent": task.intent.value,
            "expert_name": task.expert_name,
            "status": "success",
            "summary": "不应等待",
        }

    result = execute_task_with_retry(
        _task(),
        TaskContext(payload={}, runner=runner),
        max_retries=0,
        timeout_seconds=0.01,
        deadline_seconds=0.02,
    )

    assert result.status is ExpertStatus.TIMEOUT
    assert time.monotonic() - started < 0.15


def test_internal_error_is_not_leaked_into_user_visible_fields():
    """任务异常时，用户可见的 summary/error_code 不得包含异常原文。"""

    def runner(task, payload):
        raise RuntimeError("connection to postgres://user:secret@host failed")

    result = execute_task_with_retry(
        _task(),
        TaskContext(payload={}, runner=runner),
        max_retries=0,
        timeout_seconds=5,
        deadline_seconds=5,
    )

    assert result.status is ExpertStatus.FAILED
    assert result.error_code == "task_error"
    assert "postgres" not in result.summary
    assert "secret" not in result.summary
