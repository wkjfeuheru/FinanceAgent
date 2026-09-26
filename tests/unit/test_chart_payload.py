"""图表最小载荷的投影与落库口径。

历史会话要能复原图表，靠的是写助手消息时把结构化结果**精简后**存进
``conversation_messages.metadata``。这里守住三件事：

1. 只投影前端真正读的键（键位与 ``frontend/src/features/chat/chartData.ts`` 耦合）；
2. 空值不入库——"没有数据"必须是**键不存在**，而不是键存在但为空对象；
3. 全量 ``technical_analysis`` 不得进入 metadata（它可能几十 KB），否则历史行会
   无声膨胀。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from finance_agent.application.run_persistence import (
    CHART_PAYLOAD_KEYS,
    build_chart_payload,
)

_PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "finance_agent"
_PROMPT_DIRS = ("research", "portfolio", "products")


def test_projects_only_the_chart_keys() -> None:
    output: dict[str, Any] = {
        "response": "正文不应入库到图表载荷",
        "task_plan": ["stock_analysis"],
        "account": {"positions": [{"code": "600519"}]},
        "analysis_results": [{"action": "关注", "scores": {"fundamental": 62}}],
        "technical_analysis": {"600519": {"MACD": {"latest": {"DIF": 0.4}}}},
        "facts": [{"fact_id": "f1"}],
    }

    payload = build_chart_payload(output)

    assert set(payload) == set(CHART_PAYLOAD_KEYS)
    assert "response" not in payload
    assert "task_plan" not in payload
    assert "facts" not in payload


def test_empty_values_are_omitted_so_absence_is_a_missing_key() -> None:
    payload = build_chart_payload(
        {
            "analysis_results": [],
            "technical_analysis": {"600519": {"MA": {"latest": {"MA5": 1}}}},
        }
    )

    # 空 dict / 空列表不入库；只有真正有内容的键留下。
    assert set(payload) == {"technical_analysis"}


def test_missing_or_none_output_yields_empty_payload() -> None:
    assert build_chart_payload(None) == {}
    assert build_chart_payload({}) == {}


def test_payload_is_json_serializable_for_the_jsonb_column() -> None:
    import json

    payload = build_chart_payload(
        {
            "analysis_results": [{"action": "关注", "scores": {"fundamental": 62}}],
            "technical_analysis": {"600519": {"RSI": {"latest": {"RSI6": 82}}}},
        }
    )
    # `ensure_ascii=False` 与业务存储层写 metadata 时一致。
    restored = json.loads(json.dumps(payload, ensure_ascii=False))
    assert restored == payload


def test_all_expert_prompts_carry_the_output_format_rule() -> None:
    """各领域专家都必须带上输出格式约束，避免某一路继续产出满屏 Markdown。"""
    missing: list[str] = []
    for domain in _PROMPT_DIRS:
        path = _PACKAGE_ROOT / "domains" / domain / "expert" / "prompts" / "system.md"
        text = path.read_text(encoding="utf-8")
        if "## 输出格式" not in text:
            missing.append(f"{domain}: 缺少「输出格式」小节")
        if "成篇加粗" not in text:
            missing.append(f"{domain}: 缺少「不要成篇加粗」约束")
    assert not missing, "；".join(missing)
