"""回归基线校验：读取评测汇总，对关键指标做阈值断言。

供本地（``scripts/run-evals.ps1``）与 CI 使用：任一指标跌破阈值即非零退出，
让「加固能力退化」在提交时被拦住，而不是等上线才发现。

阈值取实测值的**保守下界**（留足机器抖动与数据源波动余量）：基准类指标按
加速比下限判断，正确率类指标按绝对下限判断。改语料后若阈值不再适用，
显式调整本文件的 ``THRESHOLDS`` 而不是放宽到失去意义。

    .venv/Scripts/python.exe -m evals.runners.check_baseline
    .venv/Scripts/python.exe -m evals.runners.check_baseline --summary path/to/summary.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

THRESHOLDS_PATH = Path(__file__).resolve().parents[1] / "baselines" / "thresholds.json"


def _thresholds() -> list[tuple[str, str, float, str]]:
    data = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))
    return [
        (item["metric"], item["operator"], float(item["value"]), item["label"])
        for item in data["metrics"]
    ]


def _get(data: dict, path: str) -> float:
    node: object = data
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(path)
        node = node[part]
    return node  # type: ignore[return-value]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="评测基线回归校验")
    parser.add_argument("--summary", default=".cache/evals/results/summary.json")
    args = parser.parse_args(argv)

    path = Path(args.summary)
    if not path.exists():
        print(f"[基线校验] 缺少 {path}；请先运行 `python -m evals.runners.run_all`")
        return 1
    data = json.loads(path.read_text(encoding="utf-8"))

    failures: list[str] = []
    print("[基线校验] 指标阈值：")
    for metric, op, threshold, label in _thresholds():
        try:
            value = _get(data, metric)
        except KeyError:
            failures.append(f"{metric} 缺失")
            print(f"  - {label}：**缺失**（{metric}）")
            continue
        ok = value >= threshold if op == ">=" else False
        mark = "OK" if ok else "FAIL"
        print(f"  - [{mark}] {label}：{value:.4g} {op} {threshold:.4g}")
        if not ok:
            failures.append(f"{label}：{value:.4g} < {threshold:.4g}")

    # 布尔型不变量单独校验。
    deg = data.get("degradation", {})
    served = deg.get("circuit_breaker_served_ok")
    total = deg.get("circuit_breaker_requests")
    cb_ok = isinstance(served, int) and isinstance(total, int) and total > 0 and served == total
    print(f"  - [{'OK' if cb_ok else 'FAIL'}] 数据源故障下请求成功率：{served}/{total}")
    if not cb_ok:
        failures.append(f"熔断降级未全部由备用源完成：{served}/{total}")

    if failures:
        print("\n[基线校验] 未通过，以下指标跌破阈值：")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("\n[基线校验] 通过，所有关键指标均在阈值之上。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
