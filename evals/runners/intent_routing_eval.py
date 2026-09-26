"""意图分类 → 领域路由 评测（离线回放，可选 live 模式）。

评测对象是**编排层的加固能力**，不是模型的裸能力：给定一段「模型原始 JSON 输出」，
当前代码要经过证据校验、逐条容错、意图/执行模式归一、置信度门控与领域路由，
最终产出一个 ``RoutingDecision``。本脚本把标注好的真实语料与「会被模型吐出来的
典型噪声」（execution_mode 误填进 intent、兄弟条目举证失败、低置信度、臆造意图…）
回放进这条真实代码路径，衡量路由正确率，并与一个**未加固的严格基线**做消融对比。

运行：

    .venv/Scripts/python.exe -m evals.runners.intent_routing_eval          # 离线回放
    .venv/Scripts/python.exe -m evals.runners.intent_routing_eval --live   # 额外跑真实模型

离线模式下不发起任何网络请求（注入的 RawModel 直接返回固定 payload）。
``--live`` 会调用配置中的意图模型，仅在 API key 与网络就绪时有意义。

产出：stdout 的 Markdown 报告 + ``.cache/evals/results/intent_routing_eval.json``。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

# 与 tests/conftest.py 一致：先在导入 config 前准备好测试环境变量，
# 避免 config 在导入期因缺少密钥而报错。
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

from finance_agent.orchestration.contracts import BusinessDomain  # noqa: E402
from finance_agent.orchestration.routing.intent import (  # noqa: E402
    _INTENTS,
    _INTENT_CONFIDENCE_THRESHOLD,
    _INTENT_TO_DOMAIN,
    DeepSeekIntentClassifier,
    IntentClassifier,
)
from finance_agent.orchestration.graphs.supervisor import classify_domains  # noqa: E402

_STRICT_ALLOWED_MODES = {
    "stock_analysis": {"stock_analysis", "single_analysis"},
    "stock_recommendation": {"candidate_search", "stock_comparison"},
    "product_analysis": {"product_analysis", "product_lookup", "product_evaluation"},
    "portfolio_analysis": {"allocation_review"},
    "casual_chat": {"conversation"},
}

_DOMAIN_ORDER = (
    BusinessDomain.STOCK_RESEARCH.value,
    BusinessDomain.PRODUCT_RESEARCH.value,
    BusinessDomain.ACCOUNT_PORTFOLIO.value,
)

FAIL = "<classification_failed>"


# ── 用例模型 ────────────────────────────────────────────────────────────────

@dataclass
class Case:
    """一条评测用例：消息 + 模型原始输出 + 期望路由。"""

    case_id: str
    message: str
    raw: dict
    expect_domains: tuple[str, ...]
    expect_mode: str
    tag: str = "clean"
    note: str = ""


def _intent(
    intent: str,
    query: str,
    evidence: str,
    confidence: float = 0.96,
    execution_mode: str | None = None,
) -> dict:
    return {
        "intent": intent,
        "query": query,
        "confidence": confidence,
        "reason": "评测用例",
        "evidence": evidence,
        "execution_mode": execution_mode or intent,
    }


def _payload(*items: dict, finance_related: bool = True) -> dict:
    return {"intents": list(items), "finance_related": finance_related}


# ── 标注语料 ────────────────────────────────────────────────────────────────
# 覆盖 5 类意图 / 3 个业务领域 / 闲聊 / 澄清，并混入真实世界里的模型噪声。

def build_cases() -> list[Case]:
    cases: list[Case] = []

    def add(case: Case) -> None:
        cases.append(case)

    # —— 单领域（clean）——
    m = "分析一下贵州茅台600519的基本面和技术面"
    add(Case("s1", m, _payload(_intent("stock_analysis", m, m, execution_mode="stock_analysis")),
             ("stock_research",), "domain_workflow"))

    m = "110011 怎么样"
    add(Case("s2", m, _payload(_intent("product_analysis", m, m, execution_mode="product_lookup")),
             ("product_research",), "domain_workflow"))

    m = "分析一下华夏成长基金"
    add(Case("s3", m, _payload(_intent("product_analysis", m, m, execution_mode="product_evaluation")),
             ("product_research",), "domain_workflow"))

    m = "我的持仓怎么优化"
    add(Case("s4", m, _payload(_intent("portfolio_analysis", m, m, execution_mode="allocation_review")),
             ("account_portfolio",), "domain_workflow"))

    m = "我账户里的资产配置合理吗"
    add(Case("s5", m, _payload(_intent("portfolio_analysis", m, m, execution_mode="allocation_review")),
             ("account_portfolio",), "domain_workflow"))

    m = "帮我推荐几个AI行业值得关注的股票"
    add(Case("s6", m, _payload(_intent("stock_recommendation", m, m, execution_mode="candidate_search")),
             ("stock_research",), "domain_workflow"))

    m = "比较一下宁德时代和比亚迪"
    add(Case("s7", m, _payload(_intent("stock_recommendation", m, m, execution_mode="stock_comparison")),
             ("stock_research",), "domain_workflow"))

    m = "110011 怎么样"
    add(Case("s8", m, _payload(_intent("product_analysis", m, m, execution_mode="product_analysis")),
             ("product_research",), "domain_workflow"))

    m = "分析一下华夏成长基金"
    add(Case("s9", m, _payload(_intent("product_analysis", m, m, execution_mode="product_analysis")),
             ("product_research",), "domain_workflow"))

    m = "我的持仓怎么样"
    add(Case("s10", m, _payload(_intent("casual_chat", m, m, execution_mode="conversation")),
             (), "conversation"))

    m = "我账户里还有多少钱"
    add(Case("s11", m, _payload(_intent("casual_chat", m, m, execution_mode="conversation")),
             (), "conversation"))

    m = "帮我买1000块110011"
    add(Case("s12", m, _payload(_intent("casual_chat", m, m, execution_mode="conversation")),
             (), "conversation"))

    # —— 闲聊 / 知识问答（应走 conversation，不路由业务领域）——
    m = "什么是基金的风险等级"
    add(Case("c1", m, _payload(_intent("casual_chat", m, m, execution_mode="conversation")),
             (), "conversation"))

    m = "T+1 是什么"
    add(Case("c2", m, _payload(_intent("casual_chat", m, m, execution_mode="conversation")),
             (), "conversation"))

    m = "你好呀"
    add(Case("c3", m, _payload(_intent("casual_chat", m, m, execution_mode="conversation")),
             (), "conversation"))

    # —— 复合领域（多领域扇出，与单领域同一执行模式）——
    m = "分析贵州茅台，并推荐几个合适的基金产品"
    add(Case("p1", m, _payload(
        _intent("stock_analysis", "分析贵州茅台", "分析贵州茅台", execution_mode="stock_analysis"),
        _intent("product_analysis", "推荐几个合适的基金产品", "推荐几个合适的基金产品",
                execution_mode="product_analysis"),
    ), ("stock_research", "product_research"), "domain_workflow"))

    m = "分析贵州茅台，顺便看看我的持仓配置是否合理"
    add(Case("p2", m, _payload(
        _intent("stock_analysis", "分析贵州茅台", "分析贵州茅台", execution_mode="stock_analysis"),
        _intent("portfolio_analysis", "看看我的持仓配置是否合理", "看看我的持仓配置是否合理", execution_mode="allocation_review"),
    ), ("stock_research", "account_portfolio"), "domain_workflow"))

    m = "分析600519并看看110011这只基金"
    add(Case("p3", m, _payload(
        _intent("stock_analysis", "分析600519", "分析600519", execution_mode="stock_analysis"),
        _intent("product_analysis", "看看110011这只基金", "看看110011这只基金",
                execution_mode="product_lookup"),
    ), ("stock_research", "product_research"), "domain_workflow"))

    m = "帮我看看华夏成长基金和我的账户配置要不要调整"
    add(Case("p4", m, _payload(
        _intent("product_analysis", "看看华夏成长基金", "看看华夏成长基金", execution_mode="product_lookup"),
        _intent("portfolio_analysis", "我的账户配置要不要调整", "我的账户配置要不要调整", execution_mode="allocation_review"),
    ), ("product_research", "account_portfolio"), "domain_workflow"))

    m = "分析茅台，看看110011，再看看我的持仓配置要不要调整"
    add(Case("p5", m, _payload(
        _intent("stock_analysis", "分析茅台", "分析茅台", execution_mode="stock_analysis"),
        _intent("product_analysis", "看看110011", "看看110011", execution_mode="product_lookup"),
        _intent("portfolio_analysis", "我的持仓配置要不要调整", "我的持仓配置要不要调整", execution_mode="allocation_review"),
    ), ("stock_research", "product_research", "account_portfolio"), "domain_workflow"))

    # —— 澄清（低置信度，不应执行）——
    m = "那个东西怎么样来着"
    add(Case("cl1", m, _payload(_intent("stock_analysis", m, m, confidence=0.62,
                                       execution_mode="stock_analysis")),
             (), "clarify"))

    m = "最近怎么样"
    add(Case("cl2", m, _payload(_intent("product_analysis", m, m, confidence=0.55,
                                       execution_mode="product_lookup")),
             (), "clarify"))

    # —— 噪声：模型把 execution_mode 误填进 intent 字段（可修复）——
    # 当前代码应还原为所属意图；严格基线会整批失败。
    m = "分析一下600519"
    add(Case("n1", m, _payload(
        {"intent": "single_analysis", "query": m, "confidence": 0.96,
         "reason": "", "evidence": m, "execution_mode": "single_analysis"},
    ), ("stock_research",), "domain_workflow", tag="noise:mode_as_intent",
        note="single_analysis 被当成 intent"))

    m = "帮我推荐几个AI行业的股票"
    add(Case("n2", m, _payload(
        {"intent": "candidate_search", "query": m, "confidence": 0.95,
         "reason": "", "evidence": m, "execution_mode": "candidate_search"},
    ), ("stock_research",), "domain_workflow", tag="noise:mode_as_intent",
        note="candidate_search 被当成 intent"))

    m = "我的持仓怎么优化"
    add(Case("n3", m, _payload(
        {"intent": "allocation_review", "query": m, "confidence": 0.97,
         "reason": "", "evidence": m, "execution_mode": "allocation_review"},
    ), ("account_portfolio",), "domain_workflow", tag="noise:mode_as_intent",
        note="allocation_review 被当成 intent"))

    # —— 噪声：复合请求中混入臆造意图 / 非法 execution_mode ——
    # 加固后：合法的兄弟意图必须存活；严格基线会整批失败。
    m = "分析贵州茅台，再随便给我整一个"
    add(Case("n4", m, _payload(
        _intent("stock_analysis", "分析贵州茅台", "分析贵州茅台", execution_mode="stock_analysis"),
        {"intent": "totally_unknown", "query": "随便给我整一个", "confidence": 0.9,
         "reason": "", "evidence": "随便给我整一个", "execution_mode": "totally_unknown"},
    ), ("stock_research",), "domain_workflow", tag="noise:unknown_sibling",
        note="未知 intent 兄弟条目应被丢弃，不牵连合法意图"))

    m = "分析贵州茅台，并看看110011"
    add(Case("n5", m, _payload(
        _intent("stock_analysis", "分析贵州茅台", "分析贵州茅台", execution_mode="stock_analysis"),
        {"intent": "product_analysis", "query": "看看110011", "confidence": 0.95,
         "reason": "", "evidence": "看看110011", "execution_mode": "product_mood_fake"},
    ), ("stock_research", "product_research"), "domain_workflow", tag="noise:bad_mode_sibling",
        note="非法 execution_mode 应被归一，不牵连同批合法意图"))

    # —— 噪声：兄弟条目举证失败（编造证据）——
    m = "分析贵州茅台，并推荐几个合适的基金产品"
    add(Case("n6", m, _payload(
        _intent("stock_analysis", "分析贵州茅台", "分析贵州茅台", execution_mode="stock_analysis"),
        {"intent": "product_analysis", "query": "编造的产品", "confidence": 0.95,
         "reason": "", "evidence": "这句不在原文里", "execution_mode": "product_analysis"},
    ), ("stock_research",), "domain_workflow", tag="noise:bad_evidence_sibling",
        note="编造证据的条目丢弃，合法意图保留"))

    # —— 噪声：高置信度意图 + 低置信度兄弟（后者应转澄清，不得拖垮前者）——
    m = "分析贵州茅台，顺便那个基金也看看吧"
    add(Case("n7", m, _payload(
        _intent("stock_analysis", "分析贵州茅台", "分析贵州茅台", execution_mode="stock_analysis"),
        _intent("product_analysis", "那个基金也看看", "那个基金也看看", confidence=0.7,
                execution_mode="product_analysis"),
    ), ("stock_research",), "domain_workflow", tag="noise:low_conf_sibling",
        note="低置信度兄弟转澄清，高置信度意图照常执行"))

    # —— 噪声：全部条目非法（应显式失败，不猜领域）——
    m = "嗯嗯啊啊"
    add(Case("n8", m, _payload(
        {"intent": "chit_chat_unknown", "query": m, "confidence": 0.9,
         "reason": "", "evidence": m, "execution_mode": "whatever"},
    ), (FAIL,), "clarify", tag="noise:all_invalid",
        note="无可用意图必须显式失败，禁止静默猜领域"))

    return cases


# ── 严格基线（未加固的对照实现）────────────────────────────────────────────
# 模拟「加固前」的语义：任一条目有问题即整批判定失败；不做 mode-as-intent 还原、
# 不容忍低置信度、不丢弃兄弟条目。

def strict_route(message: str, raw: dict) -> tuple[tuple[str, ...], str]:
    intents = raw.get("intents", []) if isinstance(raw, dict) else []
    if not isinstance(intents, list) or not intents:
        return (FAIL,), "clarify"
    resolved: list[str] = []
    for item in intents:
        if not isinstance(item, dict):
            return (FAIL,), "clarify"
        evidence = str(item.get("evidence", "")).strip()
        if not evidence or evidence not in message:
            return (FAIL,), "clarify"
        intent = str(item.get("intent", "")).strip()
        if intent not in _INTENTS:  # 不做 mode→intent 还原
            return (FAIL,), "clarify"
        mode = str(item.get("execution_mode", "")).strip()
        if mode not in _STRICT_ALLOWED_MODES[intent]:  # 非法模式即失败
            return (FAIL,), "clarify"
        confidence = float(item.get("confidence", 0) or 0)
        if confidence < _INTENT_CONFIDENCE_THRESHOLD:  # 低置信度即失败
            return (FAIL,), "clarify"
        resolved.append(intent)
    if not resolved:
        return (FAIL,), "clarify"
    domains = {_INTENT_TO_DOMAIN.get(intent) for intent in resolved}
    domains.discard(None)
    if not domains:
        return (), "conversation"
    ordered = tuple(sorted({d.value for d in domains}, key=_DOMAIN_ORDER.index))
    # 计划层删除后单/多领域共用同一执行模式（扇出数量不同）。
    mode = "domain_workflow"
    return ordered, mode


# ── 加固后的真实代码路径 ────────────────────────────────────────────────────

class _FakeResponse:
    """伪装成 requests.Response，把固定 payload 包成 OpenAI 兼容返回体。"""

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "choices": [
                {"message": {"content": json.dumps(self._payload, ensure_ascii=False)}}
            ]
        }


def _replay_classifier(raw: dict) -> DeepSeekIntentClassifier:
    """真实的意图分类器，但把网络请求换成本地固定返回。

    关键在于**不绕过真实代码路径**：``classify`` 仍会走 JSON 解析与
    ``_validate``（逐字证据校验、逐条容错），因此回放结果与线上一致。
    """

    def requester(*_args, **_kwargs):
        return _FakeResponse(raw)

    return DeepSeekIntentClassifier(
        api_key="eval-key",
        model="eval-model",
        timeout=1,
        max_retries=0,
        deadline=5,
        requester=requester,
    )


def hardened_route(message: str, raw: dict) -> tuple[tuple[str, ...], str]:
    classifier = IntentClassifier(classifier=_replay_classifier(raw))
    decision = classify_domains(message, "", classifier=classifier)
    if decision.error_code:
        return (FAIL,), "clarify"
    domains = tuple(
        sorted((d.value for d in decision.domains), key=_DOMAIN_ORDER.index)
    )
    return domains, decision.execution_mode


# ── Live 模式（真实模型，需要 key 与网络）──────────────────────────────────

def live_route(message: str) -> tuple[tuple[str, ...], str]:
    """调用配置中的真实意图模型；仅 --live 时使用。"""
    from finance_agent.infrastructure.settings import (
        INTENT_MODEL,
        INTENT_MODEL_API_KEY,
        INTENT_MODEL_DEADLINE,
        INTENT_MODEL_MAX_RETRIES,
        INTENT_MODEL_MAX_TOKENS,
        INTENT_MODEL_TIMEOUT,
    )
    from finance_agent.orchestration.routing.intent import DeepSeekIntentClassifier

    model = DeepSeekIntentClassifier(
        api_key=INTENT_MODEL_API_KEY,
        model=INTENT_MODEL,
        timeout=INTENT_MODEL_TIMEOUT,
        max_retries=INTENT_MODEL_MAX_RETRIES,
        max_tokens=INTENT_MODEL_MAX_TOKENS,
        deadline=INTENT_MODEL_DEADLINE,
    )
    decision = classify_domains(message, "", classifier=IntentClassifier(classifier=model))
    if decision.error_code:
        return (FAIL,), "clarify"
    domains = tuple(sorted((d.value for d in decision.domains), key=_DOMAIN_ORDER.index))
    return domains, decision.execution_mode


# ── 评测驱动 ────────────────────────────────────────────────────────────────

@dataclass
class Tally:
    total: int = 0
    hardened_ok: int = 0
    strict_ok: int = 0
    failures: list[dict] = field(default_factory=list)

    @property
    def hardened_acc(self) -> float:
        return self.hardened_ok / self.total if self.total else 0.0

    @property
    def strict_acc(self) -> float:
        return self.strict_ok / self.total if self.total else 0.0


def evaluate(cases: list[Case]) -> dict[str, Tally]:
    overall = Tally()
    by_tag: dict[str, Tally] = {}
    for case in cases:
        h_domains, h_mode = hardened_route(case.message, case.raw)
        s_domains, s_mode = strict_route(case.message, case.raw)
        h_ok = (h_domains, h_mode) == (case.expect_domains, case.expect_mode)
        s_ok = (s_domains, s_mode) == (case.expect_domains, case.expect_mode)

        for tally in (overall, by_tag.setdefault(case.tag, Tally())):
            tally.total += 1
            tally.hardened_ok += int(h_ok)
            tally.strict_ok += int(s_ok)
            if not h_ok:
                tally.failures.append({
                    "case_id": case.case_id,
                    "tag": case.tag,
                    "message": case.message,
                    "expect": {"domains": list(case.expect_domains), "mode": case.expect_mode},
                    "hardened": {"domains": list(h_domains), "mode": h_mode},
                    "strict": {"domains": list(s_domains), "mode": s_mode},
                    "note": case.note,
                })
    return {"overall": overall, **{f"tag:{k}": v for k, v in by_tag.items()}}


def render_report(tallies: dict[str, Tally]) -> str:
    overall = tallies["overall"]
    tag_keys = sorted(k for k in tallies if k.startswith("tag:"))
    noise_keys = [k for k in tag_keys if not k.endswith(":clean")]

    lines: list[str] = []
    lines.append("# 意图分类 → 领域路由 评测报告（离线回放）")
    lines.append("")
    lines.append(f"用例总数：**{overall.total}**")
    lines.append("")
    lines.append(f"- 加固后（当前代码）路由正确率：**{overall.hardened_acc:.1%}**"
                 f"（{overall.hardened_ok}/{overall.total}）")
    lines.append(f"- 严格基线（未加固对照）路由正确率：**{overall.strict_acc:.1%}**"
                 f"（{overall.strict_ok}/{overall.total}）")

    if noise_keys:
        h_noise = [tallies[k] for k in noise_keys]
        tot = sum(t.total for t in h_noise)
        h_ok = sum(t.hardened_ok for t in h_noise)
        s_ok = sum(t.strict_ok for t in h_noise)
        lines.append("")
        lines.append(f"**噪声子集**（{tot} 条，模型输出含格式/协议瑕疵）："
                     f"加固后 {h_ok}/{tot} = {h_ok / tot:.1%}，"
                     f"严格基线 {s_ok}/{tot} = {s_ok / tot:.1%}")
        lines.append("")
        lines.append("| 噪声类型 | 用例数 | 加固后 | 严格基线 |")
        lines.append("| --- | ---: | ---: | ---: |")
        for key in noise_keys:
            t = tallies[key]
            lines.append(f"| {key.split(':', 1)[1]} | {t.total} | "
                         f"{t.hardened_ok}/{t.total} | {t.strict_ok}/{t.total} |")

    lines.append("")
    lines.append("## 分组明细")
    lines.append("")
    lines.append("| 分组 | 用例数 | 加固后正确 | 严格基线正确 |")
    lines.append("| --- | ---: | ---: | ---: |")
    for key in tag_keys:
        t = tallies[key]
        lines.append(f"| {key.split(':', 1)[1]} | {t.total} | {t.hardened_ok} | {t.strict_ok} |")

    if overall.failures:
        lines.append("")
        lines.append("## 加固后仍未通过（需人工确认）")
        lines.append("")
        for f in overall.failures:
            lines.append(f"- `{f['case_id']}` [{f['tag']}] 「{f['message']}」 "
                         f"期望 {f['expect']} 实际 {f['hardened']}（{f['note']}）")
    return "\n".join(lines)


def evaluate_live(cases: list[Case]) -> dict:
    """真实模型模式：只跑 clean 用例，避免把噪声夹具当真实输入。"""
    clean = [c for c in cases if c.tag == "clean"]
    ok = 0
    mismatches: list[dict] = []
    for case in clean:
        domains, mode = live_route(case.message)
        if (domains, mode) == (case.expect_domains, case.expect_mode):
            ok += 1
        else:
            mismatches.append({
                "case_id": case.case_id, "message": case.message,
                "expect": {"domains": list(case.expect_domains), "mode": case.expect_mode},
                "got": {"domains": list(domains), "mode": mode},
            })
    return {
        "model": os.environ.get("INTENT_MODEL", ""),
        "n": len(clean),
        "correct": ok,
        "accuracy": (ok / len(clean)) if clean else 0.0,
        "mismatches": mismatches,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="意图分类 → 领域路由评测")
    parser.add_argument("--live", action="store_true", help="额外调用真实意图模型")
    parser.add_argument("--json", default=".cache/evals/results/intent_routing_eval.json")
    args = parser.parse_args(argv)

    cases = build_cases()
    tallies = evaluate(cases)
    report = render_report(tallies)
    print(report)

    out = {
        "mode": "replay",
        "overall": {
            "total": tallies["overall"].total,
            "hardened_accuracy": tallies["overall"].hardened_acc,
            "strict_accuracy": tallies["overall"].strict_acc,
        },
        "by_group": {
            key.split(":", 1)[1]: {
                "total": t.total, "hardened_ok": t.hardened_ok, "strict_ok": t.strict_ok,
            }
            for key, t in tallies.items() if key != "overall"
        },
        "failures": tallies["overall"].failures,
    }
    if args.live:
        try:
            out["live"] = evaluate_live(cases)
            print()
            print(f"## Live 模式（真实模型 {out['live']['model']}）")
            print(f"- clean 用例 {out['live']['n']} 条，"
                  f"正确 {out['live']['correct']} 条，"
                  f"准确率 {out['live']['accuracy']:.1%}")
        except Exception as exc:  # noqa: BLE001 - live 仅供人工参考
            out["live_error"] = f"{type(exc).__name__}: {exc}"
            print(f"\nLive 模式失败（不影响离线结论）：{out['live_error']}")

    path = Path(args.json)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果已写入 {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
