"""领域意图分类器（原 Supervisor 的分类职责）。

只负责“属于哪个业务领域”，不再承担任务生成或响应拼装——那两项分别由
Supervisor Graph 的路由（``orchestration/graphs/supervisor.py``）与合规出口
（``orchestration/graphs/compliance.py``）承担。分类协议错误必须显式上报，不得静默猜测。
"""

from __future__ import annotations

import json
import logging
import math
import time
from typing import Any, Callable, Dict

import requests

from finance_agent.infrastructure.settings import (
    INTENT_FALLBACK_API_KEY,
    INTENT_FALLBACK_BASE_URL,
    INTENT_FALLBACK_DEADLINE,
    INTENT_FALLBACK_MAX_RETRIES,
    INTENT_FALLBACK_MAX_TOKENS,
    INTENT_FALLBACK_MODEL,
    INTENT_FALLBACK_TIMEOUT,
    INTENT_MODEL,
    INTENT_MODEL_API_KEY,
    INTENT_MODEL_BASE_URL,
    INTENT_MODEL_DEADLINE,
    INTENT_MODEL_MAX_RETRIES,
    INTENT_MODEL_MAX_TOKENS,
    INTENT_MODEL_TIMEOUT,
)
from finance_agent.orchestration.contracts import BusinessDomain

# 分类置信度阈值：低于该值的意图不进入执行，只进入澄清。prompt 文案与下游过滤
# 逻辑共用本常量，避免只改一处导致模型行为与代码过滤规则不一致且无告警。
_INTENT_CONFIDENCE_THRESHOLD = 0.9

_INTENT_CLASSIFIER_PROMPT = f"""你是金融工作流的多意图分类器，只分类当前用户消息，不回答问题。
近期上下文摘要包含本对话之前轮次的消息，只能用于三件事：解析指代（"它""那两只""这些股票"）、补全延续性追问、把追问问具体；不得凭空新增用户没表达过的标的或意图。
"最近AI行业有什么值得投资的股票，为我推荐几个"只能输出 stock_recommendation。

允许的意图（只能填这五个之一）：
- stock_analysis：具体个股的基本面/技术面/行情
- stock_recommendation：用户想找一组股票候选，或按主题/行业/板块找标的；专家会用板块取数工具给出该板块的公开标的与规则评分（不构成推荐）。
- product_analysis：具体产品（基金/理财，句中有明确名称或 6 位产品代码）的查询与分析
- portfolio_analysis：本人持仓的配置诊断与优化参考
- casual_chat：投资知识/规则/概念问答，以及金融相关闲聊

portfolio_analysis 只处理**配置诊断与优化参考**：用户想让自己的持仓配置被分析、诊断是否合理。
判断依据是两个条件同时满足：第一人称归属（“我的/我买的/我持有的/账户/持仓/仓位/组合”）
**且**在问配置/优化/风险匹配（“怎么优化”“配置合理吗”“要不要调整”“够不够分散”“风险敞口大不大”）：
“我的持仓怎么优化”“资产配置合理吗”“要不要调整配置”“风险敞口大不大”用 portfolio_analysis。

以下**都不是** portfolio_analysis，一律归 casual_chat：
“我的持仓怎么样”“看看我的持仓明细”（纯明细查询，账户页承载）；
“我账户里还有多少钱”“我的总资产/盈亏”（纯资金查询）；
“帮我买 1000 块 110011”“我要清仓”“帮我充值”（交易诉求，对话不代客操作，商品页/持仓页承载）。

区分方法：第一人称归属 + 配置/优化/风险匹配诉求 → portfolio_analysis；
第一人称但只是查明细、查资金、想交易 → casual_chat；
问某个标的或产品的资料与好坏、与本人是否持有无关 → stock_analysis 或 product_analysis。
“我的持仓”指的是**账户页里的持仓**，绝不是某只股票或某个基金产品。

product_analysis 只处理**具体产品**（句中出现明确的基金/理财名称或 6 位产品代码）的查询与分析：
“110011 怎么样”“分析一下华夏成长基金”用 product_analysis。

stock_analysis 只回答具体个股的基本面/技术面/行情；
按主题/行业/板块找标的（如“帮我推荐几个AI行业值得关注的股票”）仍归类为 stock_recommendation：由专家用板块取数工具给出该板块的公开标的与规则评分，而不是在这里拒绝。

投资**知识、规则与概念**问答一律归 casual_chat，不得因为句中出现“基金/产品/理财”等词就判为 product_analysis：
“如何理解基金的风险等级（R1-R5）”“基金的风险等级有哪些”“什么是基金净值/最大回撤”“申购费率是多少”“T+1 是什么”
这些都是在问通用规则与概念，应输出 casual_chat。

区分方法：看这句话是否需要**某个特定产品**才能回答。
需要特定产品（要查它的资料/业绩/费率）→ product_analysis；换任意产品答案都成立（在问通用规则）→ casual_chat。

每个意图必须包含 intent、query、confidence、reason、evidence。
evidence 必须逐字摘自 current_message，不能来自上下文。query 只包含该意图对应的当前轮子请求。
**延续性追问必须结合上下文补全**：当前消息若在延续/细化上一轮的主题（如"我是稳健型选手，你有什么建议？""换成低风险的""那这两只怎么配"），必须把它补全为该主题所属领域的**一条**可执行子请求，query 写成补全后的完整请求，evidence 仍取当前消息里的原话（例如"我是稳健型选手"）。
当 confidence 小于 {_INTENT_CONFIDENCE_THRESHOLD} 时，必须返回非空 clarification_question：它必须**点名上一轮的标的或主题**（例如"您是想让我基于上一轮那两只基金给出稳健型配置建议吗？"），不得只回"请补充更具体的信息"这类与上下文无关的话；不得直接回答或执行业务。
解析用户对上轮反问的回复时，query 应结合上下文形成完整、可执行的子请求；不能重复其他已经完成的意图。
不得因为近期上下文重复输出已经完成的高置信度意图；没有新诉求就不要重复执行。
另外输出 profile_facts，只记录用户在本条消息里**明确自述**的自身事实，形如
{{"field": "risk_preference|budget_amount|holding_period|investment_goal", "value": "…", "quote": "…"}}：
quote 必须是 current_message 的逐字片段，value 必须由 quote 直接支持；
risk_preference 取值只能是 R1 低风险 / R2 中低风险 / R3 中风险 / R4 中高风险 / R5 高风险；
budget_amount 是以元为单位的数字（"10万"→100000）；holding_period 如"1年""3个月"；investment_goal 是短句。
猜测、假设、疑问、你自己的推断、助手上一轮说过的话一律不记录；没有就输出空列表。
只输出 JSON 对象：{{"intents": [...], "finance_related": true, "profile_facts": []}}。"""


class IntentClassificationError(RuntimeError):
    """意图识别不可用或返回非法协议。"""

    def __init__(self, message: str, *, error_code: str, cause: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.cause = cause


class DeepSeekIntentClassifier:
    """通过 OpenAI 兼容接口执行多轮上下文意图分类。"""

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout: float = 30,
        max_retries: int = 1,
        max_tokens: int = 512,
        deadline: float = 15,
        base_url: str = INTENT_MODEL_BASE_URL,
        requester: Callable[..., Any] = requests.post,
    ) -> None:
        self.api_key = api_key.strip()
        self.model = model.strip()
        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))
        self.max_tokens = max(1, int(max_tokens))
        self.deadline = max(0.0, float(deadline))
        self.base_url = base_url.strip()
        self.requester = requester

    @staticmethod
    def _validate(payload: Any, message: str) -> dict[str, Any]:
        if not isinstance(payload, dict) or not isinstance(payload.get("intents"), list):
            raise IntentClassificationError(
                "意图响应必须包含 intents 列表",
                error_code="intent_protocol_error", cause="invalid_schema",
            )
        raw_intents = payload["intents"]
        if not raw_intents:
            raise IntentClassificationError(
                "意图响应必须包含至少一个意图",
                error_code="intent_protocol_error", cause="empty_intents",
            )
        # 逐条筛选：只有“证据不在原文”属于本条不可用（防模型编造证据），丢弃该条
        # 而不牵连其它条目。字段级问题（未知 intent、非法 execution_mode、置信度
        # 越界、低置信度缺少澄清）一律留给下游 normalize_intent_item 容错处理：
        # 未知 intent 会被丢弃、非法 mode 会被归一、低置信度会进入 uncertain。
        # 若因为某一条的小问题就抛错，会把同一响应里**其它高置信度的有效意图一起
        # 丢掉**（例如“分析贵州茅台并比较合适的基金产品”里合法的 stock 意图）。
        valid: list[dict[str, Any]] = []
        for item in raw_intents:
            if not isinstance(item, dict):
                continue
            evidence = str(item.get("evidence", "")).strip()
            if not evidence or evidence not in message:
                continue
            valid.append(dict(item))
        if raw_intents and not valid:
            raise IntentClassificationError(
                "意图响应没有可验证的当前轮证据",
                error_code="intent_protocol_error", cause="missing_evidence",
            )
        return {
            "intents": valid,
            "finance_related": bool(payload.get("finance_related", False)),
            # 画像候选与路由协议**解耦**：一条脏候选不得把整轮路由打回分类失败
            # （那会让用户连问题都问不出去）。逐条宽松解析，脏条目直接丢弃。
            "profile_facts": normalize_profile_facts(payload.get("profile_facts")),
        }

    def classify(
        self,
        message: str,
        context_summary: str = "",
    ) -> dict[str, Any]:
        if not self.api_key:
            raise IntentClassificationError(
                "缺少意图模型 API key",
                error_code="intent_unavailable", cause="missing_api_key",
            )
        request_input = {
            "current_message": message.strip(),
            "recent_context_summary": context_summary.strip(),
        }
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _INTENT_CLASSIFIER_PROMPT},
                {"role": "user", "content": json.dumps(request_input, ensure_ascii=False)},
            ],
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
        }
        started = time.monotonic()
        error: IntentClassificationError | None = None
        for _attempt in range(self.max_retries + 1):
            remaining = self.deadline - (time.monotonic() - started)
            if remaining <= 0:
                raise IntentClassificationError(
                    "意图分类超过总 deadline",
                    error_code="intent_unavailable", cause="deadline",
                ) from error
            try:
                response = self.requester(
                    self.base_url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                    timeout=min(self.timeout, remaining),
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                try:
                    parsed = json.loads(content)
                except (TypeError, json.JSONDecodeError) as exc:
                    raise IntentClassificationError(
                        "意图响应不是合法 JSON",
                        error_code="intent_protocol_error", cause="invalid_json",
                    ) from exc
                return self._validate(parsed, message)
            except IntentClassificationError as exc:
                error = exc
            except requests.Timeout as exc:
                error = IntentClassificationError(
                    str(exc), error_code="intent_unavailable", cause="timeout",
                )
            except requests.HTTPError as exc:
                error = IntentClassificationError(
                    str(exc), error_code="intent_unavailable", cause="http",
                )
            except requests.RequestException as exc:
                error = IntentClassificationError(
                    str(exc), error_code="intent_unavailable", cause="transport",
                )
            except Exception as exc:
                error = IntentClassificationError(
                    str(exc), error_code="intent_unavailable", cause="transport",
                )
        assert error is not None
        raise error


_INTENTS = (
    "stock_analysis", "stock_recommendation",
    "product_analysis", "portfolio_analysis", "casual_chat",
)

# 意图 → 顶层业务领域（None 表示纯闲聊，不路由到任何业务领域）。
# 这是"意图归属"的唯一事实源：Supervisor Graph 直接引用本表，不再各自硬编码一份，
# 避免新增意图（如 portfolio_analysis）只在分类器登记、却在路由表缺席的漂移。
_INTENT_TO_DOMAIN: dict[str, BusinessDomain | None] = {
    "stock_analysis": BusinessDomain.STOCK_RESEARCH,
    "stock_recommendation": BusinessDomain.STOCK_RESEARCH,
    "product_analysis": BusinessDomain.PRODUCT_RESEARCH,
    "portfolio_analysis": BusinessDomain.ACCOUNT_PORTFOLIO,
    "casual_chat": None,
}
_LOGGER = logging.getLogger(__name__)


# 模型偶尔会把旧的**领域内模式名**当成 intent 填（例如把 "single_analysis" 当意图）。
# 这些值在领域里语义唯一，直接还原成所属 intent，避免一条可修复的格式错误被
# 当成分类失败（表现为"暂时无法识别该请求的业务领域"）。子意图体系本身已删除；
# 本表只为兼容历史输出与旧 checkpoint 而保留。
_MODE_TO_INTENT: dict[str, str] = {
    "single_analysis": "stock_analysis",
    "candidate_search": "stock_recommendation",
    "product_lookup": "product_analysis",
    "product_evaluation": "product_analysis",
    "question": "product_analysis",
    "allocation_review": "portfolio_analysis",
    "conversation": "casual_chat",
}


def _resolve_intent(raw_intent: str) -> str | None:
    """把 intent 归一：已知意图直接通过；模式名误填则还原所属意图。"""
    if raw_intent in _INTENTS:
        return raw_intent
    return _MODE_TO_INTENT.get(raw_intent)


#: 模型可自述的画像字段白名单（与 ``AgentMemoryContext.apply_model_facts`` 同口径）。
_PROFILE_FACT_FIELDS = ("risk_preference", "budget_amount", "holding_period", "investment_goal")
#: 候选 quote/value 的长度上限：画像只需要"用户原话 + 归一值"，长句是噪音。
_MAX_QUOTE_CHARS = 40
_MAX_VALUE_CHARS = 30


def normalize_profile_facts(raw: Any) -> list[dict[str, str]]:
    """宽松归一模型给出的画像候选：只留白名单字段，脏条目逐条丢弃。

    与 intents 的校验策略刻意不同：画像候选是**附加值**，解析失败不能牵连整轮
    路由。取值是否真的被用户原话支持，由 ``AgentMemoryContext.apply_model_facts``
    做确定性门控（逐字引用 + 值域/关键词一致），此处只做形状归一。
    """
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        field_name = str(item.get("field", "") or "").strip()
        value = str(item.get("value", "") or "").strip()
        quote = str(item.get("quote", "") or "").strip()
        if field_name not in _PROFILE_FACT_FIELDS or not value or not quote:
            continue
        fact = {
            "field": field_name,
            "value": value[:_MAX_VALUE_CHARS],
            "quote": quote[:_MAX_QUOTE_CHARS],
        }
        if fact not in out:
            out.append(fact)
    return out


def normalize_intent_item(
    item: Dict[str, Any], fallback_query: str,
) -> Dict[str, Any] | None:
    """校验单条意图并补齐其可执行路由字段。

    兼容旧协议：``sub_intent`` / ``execution_mode`` 字段仍被读取，但只用于
    **模式名误填的意图还原**（``_resolve_intent``）——子意图本身不再是路由输入，
    专家 ReAct 自主决定领域内的分析路径。
    """
    raw_intent = str(item.get("intent", "")).strip()
    intent = _resolve_intent(raw_intent)
    if intent is None:
        # 老模型可能把模式名填进 sub_intent 而非 intent：再试一次。
        legacy = str(item.get("sub_intent", "") or item.get("execution_mode", "")).strip()
        intent = _MODE_TO_INTENT.get(legacy)
        if intent is None:
            return None
    try:
        confidence = float(item.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0.0
    if not math.isfinite(confidence):
        confidence = 0.0
    return {
        "intent": intent,
        "query": str(item.get("query", "")).strip() or fallback_query.strip(),
        "confidence": min(max(confidence, 0.0), 1.0),
        "reason": str(item.get("reason", "")).strip(),
        "evidence": str(item.get("evidence", "")).strip(),
        "clarification_question": str(
            item.get("clarification_question", "")
        ).strip(),
        "clarification_id": str(item.get("clarification_id", "")).strip(),
        "clarification_ids": list(dict.fromkeys(
            [
                str(value).strip()
                for value in (
                    item.get("clarification_ids", [])
                    if isinstance(item.get("clarification_ids", []), list)
                    else []
                )
                if str(value).strip()
            ]
            + ([str(item.get("clarification_id", "")).strip()]
               if str(item.get("clarification_id", "")).strip() else [])
        )),
    }


class IntentClassifier:
    """合并本轮全部意图，产出三领域路由所需的分类结果。

    分类走**主备降级链**：主模型不可用（超时、欠费、协议错等）时自动改用
    备用模型；两者都失败才显式上报失败，不静默猜测业务领域。
    """

    def __init__(self, *, classifier: Any = None, fallback_classifier: Any = None) -> None:
        self._intent_classifier = classifier
        self._fallback_classifier = fallback_classifier
        # 注入主分类器（测试/自定义）时不自动构造联网备用模型，避免测试
        # 因降级链意外发起真实请求；此时备用只能用 fallback_classifier 显式提供。
        self._allow_config_fallback = classifier is None

    @property
    def intent_classifier(self) -> DeepSeekIntentClassifier:
        if self._intent_classifier is None:
            self._intent_classifier = DeepSeekIntentClassifier(
                api_key=INTENT_MODEL_API_KEY,
                model=INTENT_MODEL,
                timeout=INTENT_MODEL_TIMEOUT,
                max_retries=INTENT_MODEL_MAX_RETRIES,
                max_tokens=INTENT_MODEL_MAX_TOKENS,
                deadline=INTENT_MODEL_DEADLINE,
                base_url=INTENT_MODEL_BASE_URL,
            )
        return self._intent_classifier

    def _build_config_fallback(self) -> DeepSeekIntentClassifier | None:
        if not self._allow_config_fallback:
            return None
        if not (INTENT_FALLBACK_API_KEY and INTENT_FALLBACK_MODEL and INTENT_FALLBACK_BASE_URL):
            return None
        return DeepSeekIntentClassifier(
            api_key=INTENT_FALLBACK_API_KEY,
            model=INTENT_FALLBACK_MODEL,
            timeout=INTENT_FALLBACK_TIMEOUT,
            max_retries=INTENT_FALLBACK_MAX_RETRIES,
            max_tokens=INTENT_FALLBACK_MAX_TOKENS,
            deadline=INTENT_FALLBACK_DEADLINE,
            base_url=INTENT_FALLBACK_BASE_URL,
        )

    @property
    def fallback_classifier(self) -> DeepSeekIntentClassifier | None:
        if self._fallback_classifier is None:
            self._fallback_classifier = self._build_config_fallback()
        return self._fallback_classifier

    def _classify_with_model(
        self, message: str, context_summary: str,
    ) -> tuple[Dict[str, Any], str]:
        """返回 ``(分类结果, 实际使用的模型来源)``。

        主模型失败时回退备用模型；备用也不可用/失败时抛出显式分类错误。
        """
        try:
            return self.intent_classifier.classify(message, context_summary), "primary"
        except Exception as primary_exc:  # noqa: BLE001 - 主模型任何失败都尝试降级
            fallback = self.fallback_classifier
            if fallback is None:
                raise
            _LOGGER.warning(
                "intent_primary_unavailable fallback_used error=%s", primary_exc,
            )
            try:
                return fallback.classify(message, context_summary), "fallback"
            except Exception as fallback_exc:  # noqa: BLE001 - 主备均失败才上报
                raise IntentClassificationError(
                    "意图分类主备模型均不可用",
                    error_code="intent_unavailable",
                    cause=(
                        f"primary={getattr(primary_exc, 'cause', 'unknown')};"
                        f"fallback={getattr(fallback_exc, 'cause', 'unknown')}"
                    ),
                ) from fallback_exc

    def classify_intents(
        self,
        message: str,
        context_summary: str = "",
    ) -> Dict[str, Any]:
        """结合近期摘要识别并合并本轮全部意图。"""
        source = "deepseek"
        classification_error = False
        classification_error_details: dict[str, str] = {}
        try:
            parsed, model_source = self._classify_with_model(message, context_summary)
            if model_source == "fallback":
                source = "deepseek_fallback"
        except Exception as exc:
            _LOGGER.warning("intent_classifier_unavailable error=%s", exc)
            parsed = {}
            classification_error = True
            classification_error_details = {
                "error_code": getattr(exc, "error_code", "intent_unavailable"),
                "cause": getattr(exc, "cause", "unknown"),
            }

        uncertain: list[dict[str, Any]] = []

        def merge_valid(payload: Any) -> dict[str, dict[str, Any]]:
            merged_items: dict[str, dict[str, Any]] = {}
            raw_intents = payload.get("intents", []) if isinstance(payload, dict) else []
            if not isinstance(raw_intents, list):
                return merged_items
            for raw_item in raw_intents:
                if not isinstance(raw_item, dict):
                    continue
                candidate = dict(raw_item)
                item = normalize_intent_item(candidate, message)
                if item is None:
                    continue
                if item["confidence"] <= 0:
                    continue
                if item["confidence"] < _INTENT_CONFIDENCE_THRESHOLD:
                    uncertain.append(item)
                    continue
                intent = item["intent"]
                if intent in merged_items:
                    if item["query"] not in merged_items[intent]["query"]:
                        merged_items[intent]["query"] += "；" + item["query"]
                    merged_items[intent]["confidence"] = max(
                        merged_items[intent]["confidence"], item["confidence"],
                    )
                    merged_items[intent]["clarification_ids"] = list(dict.fromkeys(
                        merged_items[intent].get("clarification_ids", [])
                        + item.get("clarification_ids", [])
                    ))
                else:
                    merged_items[intent] = item
            return merged_items

        merged = merge_valid(parsed)
        profile_facts = normalize_profile_facts(
            parsed.get("profile_facts") if isinstance(parsed, dict) else None
        )
        if classification_error:
            source = "classification_error"
            merged = {}
            finance_related = False
            uncertain = []
            # 路由都没认出来，本轮不写任何长期记忆（如实降级，不猜）。
            profile_facts = []
        elif not merged and not uncertain:
            # 模型返回了 intents，但没有一条通过校验。必须标记分类失败，
            # 否则编排层只看到空字典会误判成功。
            source = "classification_error"
            finance_related = False
            classification_error_details = {
                "error_code": "intent_protocol_error",
                "cause": "no_valid_intents",
            }
        else:
            finance_related = bool(
                parsed.get("finance_related")
                if isinstance(parsed, dict) and "finance_related" in parsed
                else any(intent != "casual_chat" for intent in merged)
            )
        if uncertain and source != "classification_error":
            source = "clarification"
        order = {name: index for index, name in enumerate(_INTENTS)}
        intents = sorted(merged.values(), key=lambda item: order[item["intent"]])
        _LOGGER.info(
            "[Intent Classification] %s | source=%s",
            ", ".join(f"{item['intent']}={item['confidence']:.2f}" for item in intents),
            source,
        )
        return {
            "intents": intents,
            "uncertain_intents": uncertain,
            "finance_related": finance_related,
            "intent_source": source,
            "classification_error": classification_error_details,
            "profile_facts": profile_facts,
        }


def resolve_domain_sub_intents(
    intents: list[Dict[str, Any]],
) -> tuple[dict[str, str], list[str]]:
    """【已废弃】子意图体系已删除，恒返回空结果。

    保留空实现只为兼容仍会调用它的外部代码；专家 ReAct 自主决定领域内分析路径，
    不再由分类器指定领域内模式。
    """
    _ = intents
    return {}, []


__all__ = [
    "DeepSeekIntentClassifier",
    "IntentClassificationError",
    "IntentClassifier",
    "normalize_intent_item",
    "normalize_profile_facts",
]
