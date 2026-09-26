"""一键运行全部编排层评测，并汇总为一份带指标的摘要。

    .venv/Scripts/python.exe -m evals.runners.run_all

依次执行意图路由评测、并发收益基准、故障注入，然后打印汇总表，
并把合并结果写入 ``.cache/evals/results/summary.json``。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RESULTS = Path(".cache/evals/results")


def _load(name: str) -> dict:
    path = RESULTS / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"缺少结果文件 {path}；请先运行对应脚本")
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    from evals.runners import (
        degradation_fault_injection as fault,
        fanout_benchmark as fanout,
        intent_routing_eval as intent,
    )

    print("=" * 72)
    print("运行意图路由评测 …")
    intent.main([])
    print("=" * 72)
    print("运行并发收益基准 …")
    fanout.main([])
    print("=" * 72)
    print("运行故障注入实测 …")
    fault.main([])

    intent_res = _load("intent_routing_eval")
    fanout_res = _load("fanout_benchmark")
    fault_res = _load("degradation_fault_injection")

    four_domains = next(r for r in fanout_res["domain_fanout"] if r["domains"] == 4)
    noise = {
        k: v for k, v in intent_res["by_group"].items()
        if k.startswith("noise")
    }
    noise_total = sum(v["total"] for v in noise.values())
    noise_hardened = sum(v["hardened_ok"] for v in noise.values())
    noise_strict = sum(v["strict_ok"] for v in noise.values())

    summary = {
        "intent_routing": {
            "total_cases": intent_res["overall"]["total"],
            "hardened_accuracy": intent_res["overall"]["hardened_accuracy"],
            "strict_baseline_accuracy": intent_res["overall"]["strict_accuracy"],
            "noise_cases": noise_total,
            "noise_hardened_accuracy": noise_hardened / noise_total if noise_total else 0.0,
            "noise_strict_accuracy": noise_strict / noise_total if noise_total else 0.0,
        },
        "domain_fanout": {
            "four_domain_speedup": four_domains["speedup"],
            "four_domain_serial_s": four_domains["serial_median_s"],
            "four_domain_send_s": four_domains["send_median_s"],
            "fetch_speedups": {str(r["codes"]): r["speedup"] for r in fanout_res["fetch_parallel"]},
        },
        "degradation": {
            "intent_fallback_success_rate": min(
                r["with_fallback_success_rate"] for r in fault_res["intent_degradation"]["by_failure"]
            ),
            "intent_no_fallback_success_rate": max(
                r["without_fallback_success_rate"]
                for r in fault_res["intent_degradation"]["by_failure"]
            ),
            "circuit_breaker_served_ok": fault_res["circuit_breaker"]["served_ok"],
            "circuit_breaker_requests": fault_res["circuit_breaker"]["requests"],
            "half_open_retried": fault_res["half_open"]["half_open_retried"],
        },
    }

    lines = ["", "=" * 72, "# 汇总指标", ""]
    ir = summary["intent_routing"]
    lines.append(f"- 意图→路由 加固后正确率：**{ir['hardened_accuracy']:.1%}**"
                 f"（{ir['total_cases']} 条用例），严格基线 {ir['strict_baseline_accuracy']:.1%}")
    lines.append(f"- 噪声子集（{ir['noise_cases']} 条）：加固后 "
                 f"**{ir['noise_hardened_accuracy']:.1%}** vs 基线 {ir['noise_strict_accuracy']:.1%}")
    df = summary["domain_fanout"]
    lines.append(f"- 4 领域扇出加速比：**{df['four_domain_speedup']:.2f}x**"
                 f"（{df['four_domain_serial_s']:.3f}s → {df['four_domain_send_s']:.3f}s）")
    lines.append(f"- 多标的取数加速比（3/6/10 标的）："
                 f"{', '.join(f'{v:.2f}x' for v in df['fetch_speedups'].values())}")
    dg = summary["degradation"]
    lines.append(f"- 意图主模型故障下有降级链成功率：**{dg['intent_fallback_success_rate']:.0%}**"
                 f"（无降级链 {dg['intent_no_fallback_success_rate']:.0%}）")
    lines.append(f"- 数据源故障下请求成功率：**{dg['circuit_breaker_served_ok']}/"
                 f"{dg['circuit_breaker_requests']}**（全程由备用源完成）")
    print("\n".join(lines))

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(f"\n汇总已写入 {RESULTS / 'summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
