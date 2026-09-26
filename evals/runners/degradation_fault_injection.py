"""故障注入：可用性兜底实测（意图主备降级 + 数据源熔断降级）。

模拟两类真实故障，验证系统是否「降级但不中断」，并量化每次请求多付的代价：

1. **意图分类主模型故障**：主模型连续超时/HTTP 错误/协议错/额度耗尽，
   分类器应自动切到备用模型，请求成功率保持 100%；两个模型都挂才显式失败。
   对照组是「无降级链」时同一故障序列下的成功率。
2. **数据源故障与熔断**：首选源连续失败达到阈值后应被熔断（冷却期内不再
   重付超时代价），请求由次选源完成；冷却结束进入半开、重试一次。
   对照组是「无熔断」时每轮都重试故障源所付的累计耗时。

全部使用内存桩，不发网络请求。运行：

    .venv/Scripts/python.exe -m evals.runners.degradation_fault_injection

产出：stdout 的 Markdown 报告 + ``.cache/evals/results/degradation_fault_injection.json``。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

import requests  # noqa: E402

from finance_agent.infrastructure.market_data.provider_manager import ProviderManager  # noqa: E402
from finance_agent.infrastructure.market_data.providers import (  # noqa: E402
    ProviderTimeoutError,
    UnsupportedProviderCapability,
)
from finance_agent.orchestration.routing.intent import (  # noqa: E402
    DeepSeekIntentClassifier,
    IntentClassificationError,
    IntentClassifier,
)


# ── 1. 意图分类主备降级 ─────────────────────────────────────────────────────

def _valid_payload(message: str) -> dict:
    return {
        "intents": [{
            "intent": "stock_analysis", "query": message, "confidence": 0.96,
            "reason": "", "evidence": message, "execution_mode": "stock_analysis",
        }],
        "finance_related": True,
    }


class _Resp:
    """伪装成 requests.Response：可携带 HTTP 错误或一段原始文本内容。"""

    def __init__(self, *, status_error=None, payload_text=None):
        self._status_error = status_error
        self._payload_text = payload_text

    def raise_for_status(self):
        if self._status_error:
            raise self._status_error

    def json(self):
        return {"choices": [{"message": {"content": self._payload_text}}]}


def _failing_requester(failure: str):
    """按故障类型返回一个必定失败的 requester。"""

    def requester(*_args, **_kwargs):
        if failure == "timeout":
            raise requests.Timeout("upstream slow")
        if failure == "http":
            return _Resp(status_error=requests.HTTPError("503"))
        if failure == "quota":
            return _Resp(status_error=requests.HTTPError("429 insufficient balance"))
        if failure == "protocol":
            return _Resp(payload_text="这不是 JSON")
        raise AssertionError(failure)

    return requester


def _ok_requester(message: str):
    def requester(*_args, **_kwargs):
        return _Resp(payload_text=json.dumps(_valid_payload(message), ensure_ascii=False))

    return requester


def bench_intent_degradation(failures: list[str], repeats: int) -> dict:
    message = "分析600519"
    detail: list[dict] = []
    for failure in failures:
        primary = DeepSeekIntentClassifier(
            api_key="k", model="qwen-turbo", timeout=1, max_retries=0, deadline=5,
            requester=_failing_requester(failure),
        )
        fallback = DeepSeekIntentClassifier(
            api_key="k", model="deepseek-chat", timeout=1, max_retries=0, deadline=5,
            requester=_ok_requester(message),
        )
        classifier = IntentClassifier(classifier=primary, fallback_classifier=fallback)

        chain_ok = 0
        no_chain_ok = 0
        for _ in range(repeats):
            result = classifier.classify_intents(message)
            if result["intents"] and not result["classification_error"]:
                chain_ok += 1
            # 对照组：只有主模型，无降级链。
            try:
                primary.classify(message)
                no_chain_ok += 1
            except IntentClassificationError:
                pass
        detail.append({
            "failure": failure,
            "with_fallback_success_rate": chain_ok / repeats,
            "without_fallback_success_rate": no_chain_ok / repeats,
        })

    # 两个模型都挂：必须显式失败，绝不静默猜领域。
    both_down = IntentClassifier(
        classifier=DeepSeekIntentClassifier(
            api_key="k", model="p", timeout=1, max_retries=0, deadline=5,
            requester=_failing_requester("http"),
        ),
        fallback_classifier=DeepSeekIntentClassifier(
            api_key="k", model="f", timeout=1, max_retries=0, deadline=5,
            requester=_failing_requester("timeout"),
        ),
    )
    both = both_down.classify_intents(message)

    return {
        "repeats": repeats,
        "by_failure": detail,
        "both_down": {
            "intents_empty": both["intents"] == [],
            "error_code": both["classification_error"].get("error_code"),
            "cause": both["classification_error"].get("cause"),
        },
    }


# ── 2. 数据源故障与熔断 ─────────────────────────────────────────────────────

class _FakeProvider:
    """可配置单个方法行为的 Provider 桩；记录被调用次数。"""

    def __init__(self, name: str, *, error: Exception | None = None,
                 delay: float = 0.0, daily: list | None = None,
                 unsupported: bool = False):
        self.provider_name = name
        self._error = error
        self._delay = delay
        self._daily = daily if daily is not None else [{"trade_date": "20260101", "close": 10.0}]
        self._unsupported = unsupported
        self.calls = 0

    def is_available(self) -> bool:
        return True

    def _run(self):
        self.calls += 1
        if self._delay:
            time.sleep(self._delay)
        if self._error is not None:
            raise self._error
        if self._unsupported:
            raise UnsupportedProviderCapability(f"{self.provider_name} 不支持")
        return self._daily

    def get_daily(self, stock_code, start_date="", end_date="", adjustment="raw"):
        return self._run()


def bench_circuit_breaker(threshold: int, cooldown: float, requests_n: int,
                          primary_delay: float, secondary_delay: float) -> dict:
    primary = _FakeProvider("akshare", error=ProviderTimeoutError("timeout"),
                            delay=primary_delay)
    secondary = _FakeProvider("baostock", delay=secondary_delay)

    with_breaker = ProviderManager(
        providers={"akshare": primary, "baostock": secondary},
        order=["akshare", "baostock"],
        call_timeout=0,
        failure_threshold=threshold,
        cooldown=cooldown,
    )
    started = time.monotonic()
    served_ok = 0
    for _ in range(requests_n):
        result = with_breaker.get_daily("600519")
        if result and with_breaker.last_metadata["source"] == "baostock":
            served_ok += 1
    breaker_elapsed = time.monotonic() - started
    primary_calls_with_breaker = primary.calls

    # 对照组：无熔断（阈值为 0 表示永不熔断），每轮都重试故障源。
    primary_no = _FakeProvider("akshare", error=ProviderTimeoutError("timeout"),
                               delay=primary_delay)
    secondary_no = _FakeProvider("baostock", delay=secondary_delay)
    no_breaker = ProviderManager(
        providers={"akshare": primary_no, "baostock": secondary_no},
        order=["akshare", "baostock"],
        call_timeout=0,
        failure_threshold=0,
        cooldown=cooldown,
    )
    started = time.monotonic()
    for _ in range(requests_n):
        no_breaker.get_daily("600519")
    no_breaker_elapsed = time.monotonic() - started

    return {
        "threshold": threshold,
        "cooldown_s": cooldown,
        "requests": requests_n,
        "served_ok": served_ok,
        "primary_calls_with_breaker": primary_calls_with_breaker,
        "primary_calls_without_breaker": primary_no.calls,
        "elapsed_with_breaker_s": breaker_elapsed,
        "elapsed_without_breaker_s": no_breaker_elapsed,
    }


def bench_half_open(cooldown: float) -> dict:
    """冷却结束应进入半开：重试一次故障源，仍失败则再次熔断。"""
    primary = _FakeProvider("akshare", error=ProviderTimeoutError("timeout"))
    secondary = _FakeProvider("baostock")
    manager = ProviderManager(
        providers={"akshare": primary, "baostock": secondary},
        order=["akshare", "baostock"],
        call_timeout=0,
        failure_threshold=2,
        cooldown=cooldown,
    )
    manager.get_daily("600519")
    manager.get_daily("600519")  # 首次达到阈值，后续进入熔断
    before = primary.calls
    time.sleep(cooldown + 0.05)  # 等冷却结束
    manager.get_daily("600519")  # 半开：应重试一次
    after = primary.calls
    return {
        "primary_calls_before_cooldown_end": before,
        "primary_calls_after_one_half_open_probe": after,
        "half_open_retried": after > before,
    }


# ── 汇总 ────────────────────────────────────────────────────────────────────

def run(repeats: int, requests_n: int) -> dict:
    failures = ["timeout", "http", "quota", "protocol"]
    return {
        "config": {"repeats": repeats, "requests": requests_n},
        "intent_degradation": bench_intent_degradation(failures, repeats),
        "circuit_breaker": bench_circuit_breaker(
            threshold=3, cooldown=0.3, requests_n=requests_n,
            primary_delay=0.05, secondary_delay=0.05,
        ),
        "half_open": bench_half_open(cooldown=0.2),
    }


def render(results: dict) -> str:
    lines = ["# 故障注入：可用性兜底实测", ""]

    intent = results["intent_degradation"]
    lines.append("## 1. 意图分类主备降级链")
    lines.append("")
    lines.append(f"同一故障序列重复 {intent['repeats']} 次：")
    lines.append("")
    lines.append("| 主模型故障类型 | 有降级链成功率 | 无降级链成功率 |")
    lines.append("| --- | ---: | ---: |")
    for row in intent["by_failure"]:
        lines.append(
            f"| {row['failure']} | {row['with_fallback_success_rate']:.0%} | "
            f"{row['without_fallback_success_rate']:.0%} |"
        )
    both = intent["both_down"]
    lines.append("")
    lines.append(f"主备均故障：显式失败 = **{both['intents_empty']}**，"
                 f"错误码 `{both['error_code']}`，cause=`{both['cause']}`"
                 f"（不静默猜领域）")

    cb = results["circuit_breaker"]
    lines.append("")
    lines.append("## 2. 数据源熔断降级")
    lines.append("")
    lines.append(f"首选源持续故障，共 {cb['requests']} 次请求，阈值 {cb['threshold']} 次触发熔断：")
    lines.append("")
    lines.append(f"- 请求全部由次选源成功完成：**{cb['served_ok']}/{cb['requests']}**")
    lines.append(f"- 故障源被调用次数：有熔断 **{cb['primary_calls_with_breaker']}** 次 "
                 f"vs 无熔断 {cb['primary_calls_without_breaker']} 次")
    lines.append(f"- 累计耗时：有熔断 **{cb['elapsed_with_breaker_s']:.3f}s** "
                 f"vs 无熔断 {cb['elapsed_without_breaker_s']:.3f}s "
                 f"（节省 {cb['elapsed_without_breaker_s'] - cb['elapsed_with_breaker_s']:.3f}s）")

    ho = results["half_open"]
    lines.append("")
    lines.append("## 3. 冷却后半开探测")
    lines.append("")
    lines.append(f"- 冷却结束后重试故障源一次：**{'是' if ho['half_open_retried'] else '否'}**"
                 f"（{ho['primary_calls_before_cooldown_end']} → "
                 f"{ho['primary_calls_after_one_half_open_probe']} 次）")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="故障注入与降级实测")
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--requests", type=int, default=10)
    parser.add_argument("--verbose", action="store_true",
                        help="保留降级路径的 warning 日志（默认静默，只留报告）")
    parser.add_argument("--json", default=".cache/evals/results/degradation_fault_injection.json")
    args = parser.parse_args(argv)

    if not args.verbose:
        # 故障注入会刻意制造大量失败，降级 warning 属于预期噪音；默认静默，
        # 只输出结构化报告。需要排查时用 --verbose 恢复。
        logging.disable(logging.CRITICAL)

    results = run(args.repeats, args.requests)
    print(render(results))

    path = Path(args.json)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果已写入 {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
