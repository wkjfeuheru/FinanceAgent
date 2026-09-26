"""编排扇出与多标的取数的并发收益基准。

对比「同一份工作量」的两种执行方式，量化并发相对串行的墙钟收益：

1. **跨领域扇出**：串行执行器（逐个领域调用 ``domain_runner``） vs 根图
   （``scope_tasks`` → ``Send`` 扇出，同一超步内并发执行 ``domain_worker``）。
   跨领域扇出是**纯并行**：计划层删除后不再有领域间依赖，因此这里不度量 DAG
   语义（旧基准第 3 节度量的是已删除的能力）。
2. **多标的行情/财务取数**：线程池并行 vs 逐个标的顺序取数。

所有 domain_runner / fetch 都用固定 sleep 模拟真实 IO 与 CPU 混合耗时，
不发网络请求。运行：

    .venv/Scripts/python.exe -m evals.runners.fanout_benchmark

产出：stdout 的 Markdown 表格 + ``.cache/evals/results/fanout_benchmark.json``。
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

from finance_agent.orchestration.contracts import (  # noqa: E402
    BusinessDomain,
    DomainOutcome,
)
from finance_agent.orchestration.graphs.supervisor import (  # noqa: E402
    SupervisorDependencies,
    build_supervisor_graph,
)

_MAX_FETCH_WORKERS = 5

_DOMAINS = [
    BusinessDomain.STOCK_RESEARCH,
    BusinessDomain.MARKET_INSIGHT,
    BusinessDomain.PRODUCT_RESEARCH,
    BusinessDomain.ACCOUNT_PORTFOLIO,
]

#: 意图 → 领域（基准用固定的分类结果，不调模型）。
_INTENT_FOR = {
    BusinessDomain.STOCK_RESEARCH: "stock_analysis",
    BusinessDomain.MARKET_INSIGHT: "market_insight",
    BusinessDomain.PRODUCT_RESEARCH: "product_analysis",
    BusinessDomain.ACCOUNT_PORTFOLIO: "portfolio_analysis",
}


class _FixedClassifier:
    """把预设领域当作分类结果返回（基准只关心扇出，不关心分类）。"""

    def __init__(self, domains: list[BusinessDomain]) -> None:
        self._intents = [_INTENT_FOR[domain] for domain in domains]

    def classify_intents(self, message: str, context_summary: str = "") -> dict:
        return {
            "intents": [
                {"intent": intent, "query": message, "confidence": 0.99}
                for intent in self._intents
            ],
            "uncertain_intents": [],
            "finance_related": True,
            "intent_source": "eval",
            "classification_error": {},
        }


class _FakeSynthesisModel:
    """汇合节点用的假模型：基准不度量模型耗时，也绝不发真实请求。"""

    def invoke(self, messages):  # noqa: ANN001 - langchain 调用形状
        return SimpleNamespace(content="合并后的结论")


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


# ── 基准 1：跨领域扇出 ──────────────────────────────────────────────────────


def bench_serial(domains: list[BusinessDomain], seconds: float, repeats: int) -> list[float]:
    runner = _sleeping_runner(seconds)
    samples: list[float] = []
    for _ in range(repeats):
        started = time.monotonic()
        for index, domain in enumerate(domains):
            runner(SimpleNamespace(task=SimpleNamespace(
                task_id=f"{domain.value}-{index}", domain=domain,
            )))
        samples.append(time.monotonic() - started)
    return samples


def bench_send(domains: list[BusinessDomain], seconds: float, repeats: int) -> list[float]:
    graph = build_supervisor_graph(
        SupervisorDependencies(
            classifier=_FixedClassifier(domains),
            domain_runner=_sleeping_runner(seconds),
            rewriter=lambda state, domains: {},
            synthesis_model=_FakeSynthesisModel(),
        )
    )
    message = "；".join(domain.value for domain in domains)
    samples: list[float] = []
    for _ in range(repeats):
        started = time.monotonic()
        graph.invoke({
            "user_message": message,
            "history": "",
            "thread_id": "v1:EVAL:conv",
            "run_id": "eval",
            "customer_id": "EVAL",
            "conversation_id": "conv",
            "user_profile": {},
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
    fetch = _sleeping_fetch(seconds)
    samples: list[float] = []
    for _ in range(repeats):
        started = time.monotonic()
        merged: dict = {}
        for code in codes:
            merged.update(fetch([code]) or {})
        samples.append(time.monotonic() - started)
    return samples


def bench_fetch_parallel(codes: list[str], seconds: float, repeats: int) -> list[float]:
    fetch = _sleeping_fetch(seconds)
    samples: list[float] = []
    for _ in range(repeats):
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=min(_MAX_FETCH_WORKERS, len(codes))) as pool:
            list(pool.map(lambda code: fetch([code]), codes))
        samples.append(time.monotonic() - started)
    return samples


# ── 汇总 ────────────────────────────────────────────────────────────────────

def _med(xs: list[float]) -> float:
    return statistics.median(xs)


def run(seconds_domain: float, seconds_fetch: float, repeats: int) -> dict:
    results: dict = {
        "config": {
            "domain_task_seconds": seconds_domain,
            "fetch_seconds": seconds_fetch,
            "repeats": repeats,
        },
        "domain_fanout": [],
        "fetch_parallel": [],
    }

    for n in (2, 3, 4):
        if n > len(_DOMAINS):
            continue
        domains = _DOMAINS[:n]
        serial = bench_serial(domains, seconds_domain, repeats)
        send = bench_send(domains, seconds_domain, repeats)
        results["domain_fanout"].append({
            "domains": n,
            "serial_median_s": _med(serial),
            "send_median_s": _med(send),
            "ideal_parallel_s": seconds_domain * n,
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

    return results


def render(results: dict) -> str:
    cfg = results["config"]
    lines = ["# 编排扇出与多标的取数 并发收益基准", ""]
    lines.append(f"参数：领域任务 {cfg['domain_task_seconds']}s/个，取数 "
                 f"{cfg['fetch_seconds']}s/标的，每组重复 {cfg['repeats']} 次取中位数。")
    lines.append("")
    lines.append("## 1. 跨领域扇出：串行 vs 根图 Send")
    lines.append("")
    lines.append("| 领域数 | 串行执行器(s) | Send 扇出(s) | 理论并行(s) | 加速比 |")
    lines.append("| ---: | ---: | ---: | ---: | ---: |")
    for row in results["domain_fanout"]:
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
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="编排扇出并发收益基准")
    parser.add_argument("--domain-seconds", type=float, default=0.4)
    parser.add_argument("--fetch-seconds", type=float, default=0.3)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--json", default=".cache/evals/results/fanout_benchmark.json")
    args = parser.parse_args(argv)

    results = run(args.domain_seconds, args.fetch_seconds, args.repeats)
    print(render(results))

    path = Path(args.json)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果已写入 {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
