"""编排扇出与多标的取数的并发收益基准。

对比三种「同一份工作量」的执行方式，量化并发相对串行的墙钟收益：

1. **跨领域计划扇出**：串行执行器 ``run_plan_execute``（逐个任务调用
   ``domain_runner``） vs 编译后的 LangGraph 计划子图（``Send`` 扇出，
   同一超步内并发执行 ``domain_worker``）。
2. **多标的行情/财务取数**：``fetch_stock_data_parallel``（线程池） vs
   逐个标的的顺序取数。
3. **带依赖的计划**：验证 DAG 依赖语义下并发仍然生效（无依赖任务并行、
   有依赖任务等待上游），排除「并发破坏了依赖顺序」的可能。

所有 domain_runner / fetch 都用固定 sleep 模拟真实 IO 与 CPU 混合耗时，
不发网络请求。运行：

    .venv/Scripts/python.exe -m evals.plan_fanout_benchmark

产出：stdout 的 Markdown 表格 + ``evals/results/plan_fanout_benchmark.json``。
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

from finance_agent.orchestrator.contracts import (  # noqa: E402
    BusinessDomain,
    DomainOutcome,
    ExecutionPlan,
    PlanTask,
)
from finance_agent.orchestrator.domains.stock import (  # noqa: E402
    StockDeps,
    fetch_stock_data_parallel,
    _MAX_FETCH_WORKERS,
)
from finance_agent.orchestrator.graphs.plan_execute_graph import (  # noqa: E402
    build_plan_execute_graph,
    run_plan_execute,
)

_DOMAINS = [
    BusinessDomain.STOCK_RESEARCH,
    BusinessDomain.MARKET_INSIGHT,
    BusinessDomain.PRODUCT_RESEARCH,
    BusinessDomain.ACCOUNT_PORTFOLIO,
]


def _plan(n: int) -> ExecutionPlan:
    return ExecutionPlan(tasks=[
        PlanTask(
            task_id=f"plan:{domain.value}",
            domain=domain,
            goal=domain.value,
            instruction=domain.value,
            expected_output="domain_outcome",
        )
        for domain in _DOMAINS[:n]
    ])


def _sleeping_runner(seconds: float):
    def runner(context):
        time.sleep(seconds)
        return DomainOutcome(
            task_id=context.task.task_id,
            domain=context.task.domain,
            status="success",
            summary="ok",
        )

    return runner


# ── 基准 1：跨领域计划扇出 ──────────────────────────────────────────────────

def bench_serial(plan: ExecutionPlan, seconds: float, repeats: int) -> list[float]:
    samples: list[float] = []
    for _ in range(repeats):
        started = time.monotonic()
        run_plan_execute(
            domain_runner=_sleeping_runner(seconds),
            initial_plan=plan,
            thread_id="v1:EVAL:conv",
            run_id="eval",
            customer_id="EVAL",
            conversation_id="conv",
            user_message="bench",
        )
        samples.append(time.monotonic() - started)
    return samples


def bench_send(plan: ExecutionPlan, seconds: float, repeats: int) -> list[float]:
    graph = build_plan_execute_graph(
        domain_runner=_sleeping_runner(seconds),
        planner=lambda _state, _domains: plan,
    )
    domains = [task.domain.value for task in plan.tasks]
    samples: list[float] = []
    for _ in range(repeats):
        started = time.monotonic()
        graph.invoke({
            "domains": domains,
            "routing": {},
            "thread_id": "v1:EVAL:conv",
            "run_id": "eval",
            "customer_id": "EVAL",
            "conversation_id": "conv",
            "user_message": "bench",
        })
        samples.append(time.monotonic() - started)
    return samples


# ── 基准 2：多标的取数 ──────────────────────────────────────────────────────

def _sleeping_fetch(seconds: float):
    def fetch(codes: list[str]) -> dict:
        time.sleep(seconds)
        return {code: {"close": 10.0} for code in codes}

    return fetch


def bench_fetch_serial(codes: list[str], seconds: float, repeats: int) -> list[float]:
    deps = StockDeps(fetch=_sleeping_fetch(seconds))
    samples: list[float] = []
    for _ in range(repeats):
        started = time.monotonic()
        merged: dict = {}
        for code in codes:
            merged.update(deps.fetch([code]) or {})
        samples.append(time.monotonic() - started)
    return samples


def bench_fetch_parallel(codes: list[str], seconds: float, repeats: int) -> list[float]:
    deps = StockDeps(fetch=_sleeping_fetch(seconds))
    samples: list[float] = []
    for _ in range(repeats):
        started = time.monotonic()
        fetch_stock_data_parallel(deps, codes, {})
        samples.append(time.monotonic() - started)
    return samples


# ── 基准 3：带依赖的计划仍并发（依赖语义不被破坏）──────────────────────────

def bench_dependency_dag(seconds: float, repeats: int) -> dict:
    """两条独立链（各带一个依赖）——理想墙钟 = 2 层 × seconds。"""
    plan = ExecutionPlan(tasks=[
        PlanTask(task_id="a1", domain=BusinessDomain.STOCK_RESEARCH,
                 goal="a1", instruction="a1", expected_output="domain_outcome"),
        PlanTask(task_id="a2", domain=BusinessDomain.STOCK_RESEARCH,
                 goal="a2", instruction="a2", depends_on=["a1"], expected_output="domain_outcome"),
        PlanTask(task_id="b1", domain=BusinessDomain.MARKET_INSIGHT,
                 goal="b1", instruction="b1", expected_output="domain_outcome"),
        PlanTask(task_id="b2", domain=BusinessDomain.MARKET_INSIGHT,
                 goal="b2", instruction="b2", depends_on=["b1"], expected_output="domain_outcome"),
    ])
    order: list[str] = []

    def runner(context):
        order.append(context.task.task_id)
        time.sleep(seconds)
        return DomainOutcome(
            task_id=context.task.task_id, domain=context.task.domain,
            status="success", summary="ok",
        )

    graph = build_plan_execute_graph(domain_runner=runner, planner=lambda _s, _d: plan)
    samples: list[float] = []
    for _ in range(repeats):
        started = time.monotonic()
        graph.invoke({
            "domains": ["stock_research", "market_insight"],
            "routing": {}, "thread_id": "v1:EVAL:conv", "run_id": "eval",
            "customer_id": "EVAL", "conversation_id": "conv", "user_message": "bench",
        })
        samples.append(time.monotonic() - started)

    deps_ok = order.index("a1") < order.index("a2") and order.index("b1") < order.index("b2")
    return {
        "median_seconds": statistics.median(samples),
        "serial_equivalent_seconds": seconds * len(plan.tasks),
        "dependency_order_preserved": deps_ok,
        "observed_order": order[: len(plan.tasks)],
    }


# ── 汇总 ────────────────────────────────────────────────────────────────────

def _med(xs: list[float]) -> float:
    return statistics.median(xs)


def run(seconds_plan: float, seconds_fetch: float, repeats: int) -> dict:
    results: dict = {"config": {
        "plan_task_seconds": seconds_plan,
        "fetch_seconds": seconds_fetch,
        "repeats": repeats,
    }, "plan_fanout": [], "fetch_parallel": [], "dependency_dag": None}

    for n in (2, 3, 4):
        if n > len(_DOMAINS):
            continue
        plan = _plan(n)
        serial = bench_serial(plan, seconds_plan, repeats)
        send = bench_send(plan, seconds_plan, repeats)
        ideal = seconds_plan * n
        results["plan_fanout"].append({
            "domains": n,
            "serial_median_s": _med(serial),
            "send_median_s": _med(send),
            "ideal_parallel_s": ideal,
            "speedup": _med(serial) / _med(send) if _med(send) else 0.0,
        })

    for n in (3, 6, 10):
        codes = [f"{600000 + i:06d}" for i in range(n)]
        serial = bench_fetch_serial(codes, seconds_fetch, repeats)
        parallel = bench_fetch_parallel(codes, seconds_fetch, repeats)
        results["fetch_parallel"].append({
            "codes": n,
            "workers": min(_MAX_FETCH_WORKERS, n),
            "serial_median_s": _med(serial),
            "parallel_median_s": _med(parallel),
            "speedup": _med(serial) / _med(parallel) if _med(parallel) else 0.0,
        })

    results["dependency_dag"] = bench_dependency_dag(seconds_plan, repeats)
    return results


def render(results: dict) -> str:
    cfg = results["config"]
    lines = ["# 编排扇出与多标的取数 并发收益基准", ""]
    lines.append(f"参数：计划任务 {cfg['plan_task_seconds']}s/个，取数 "
                 f"{cfg['fetch_seconds']}s/标的，每组重复 {cfg['repeats']} 次取中位数。")
    lines.append("")
    lines.append("## 1. 跨领域计划扇出：串行 vs LangGraph Send")
    lines.append("")
    lines.append("| 领域数 | 串行执行器(s) | Send 扇出(s) | 理论并行(s) | 加速比 |")
    lines.append("| ---: | ---: | ---: | ---: | ---: |")
    for row in results["plan_fanout"]:
        lines.append(
            f"| {row['domains']} | {row['serial_median_s']:.3f} | "
            f"{row['send_median_s']:.3f} | {row['ideal_parallel_s']:.3f} | "
            f"{row['speedup']:.2f}x |"
        )

    lines.append("")
    lines.append("## 2. 多标的取数：顺序 vs 线程池并行")
    lines.append("")
    lines.append("| 标的数 | 并发度 | 顺序(s) | 并行(s) | 加速比 |")
    lines.append("| ---: | ---: | ---: | ---: | ---: |")
    for row in results["fetch_parallel"]:
        lines.append(
            f"| {row['codes']} | {row['workers']} | {row['serial_median_s']:.3f} | "
            f"{row['parallel_median_s']:.3f} | {row['speedup']:.2f}x |"
        )

    dag = results["dependency_dag"]
    lines.append("")
    lines.append("## 3. 带依赖的 DAG：并发不破坏依赖顺序")
    lines.append("")
    lines.append(f"- 2 条各含 1 个依赖的任务链，实测中位数 "
                 f"{dag['median_seconds']:.3f}s（全串行等价 "
                 f"{dag['serial_equivalent_seconds']:.3f}s）")
    lines.append(f"- 依赖顺序保持：**{'是' if dag['dependency_order_preserved'] else '否'}**"
                 f"，观测执行序 {dag['observed_order']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="编排扇出并发收益基准")
    parser.add_argument("--plan-seconds", type=float, default=0.4)
    parser.add_argument("--fetch-seconds", type=float, default=0.3)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--json", default="evals/results/plan_fanout_benchmark.json")
    args = parser.parse_args(argv)

    results = run(args.plan_seconds, args.fetch_seconds, args.repeats)
    print(render(results))

    path = Path(args.json)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果已写入 {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
