"""意图后置槽位提取层（Slot Extraction Layer）。

在总管（ManagerAgent）完成意图识别并生成 ``task_dispatch`` 之后、路由到具体
专家之前运行。职责：为每个意图抽取该意图对应的专家所需的**结构化入参槽位**，
并处理四类边界：

- **否定表达**：识别"不要/别/除了…以外/排除/避免/不想"等，把被否定对象
  单独提取为 ``excluded``，不混入正向 ``stock_codes``。
- **歧义**：一个名称（如"平安"/"茅台"）可能命中多只股票，本层不武断选择，
  而是标记 ``ambiguity`` 并生成澄清问题。
- **多轮合并与更新**：以 ``state["intent_slots"]`` 为跨轮载体，本轮只在用户
  明确补充/修改/否定时覆盖旧值，而不是整轮覆盖丢失（否定则清空/移除）。
- **严格对齐入参 schema**：只输出目标专家需求的结构化字段；工具参数通常要求
  **股票代码**，因此用户给名称时先调用名称→代码映射（本地全量股票表 + 常用别名）。

正常情况下使用 DeepSeek 抽取（``get_model_for_agent("slot_extraction")``，
对应 config 中 temperature=0.1 的低温策略）；LLM 不可用时降级为确定性抽取。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from finance_agent.config import get_model_for_agent, safe_parse_json
from finance_agent.data.provider_manager import get_provider_manager
from finance_agent.orchestrator.tools.stockdata import _first_value, _records

logger = logging.getLogger(__name__)

# 常用品牌/简称 → 代码。仅收录**无歧义**的常用名，用于用户用俗称时的兜底；
# 全称（如"贵州茅台"）优先走精确名称匹配。带歧义的（如"平安"）不入表，
# 交由 ambiguity 逻辑处理。
_STOCK_ALIASES: Dict[str, str] = {
    "茅台": "600519",
    "五粮液": "000858",
    "宁王": "300750",
    "宁德": "300750",
}

_SLOT_CODES = "stock_codes"
_SLOT_NAMES = "stock_names"
_SLOT_EXCLUDED = "excluded"
_SLOT_THEMES = "themes"

# 正则
_VALID_CODE_RE = re.compile(r"(?<!\d)(60\d{4}|00\d{4}|30\d{4}|68\d{4}|8\d{5}|4\d{5})(?!\d)")
# 否定表达：捕获否定词后的对象（跳过 推荐/买/持有 等常见搭配动词）
_NEGATION_RE = re.compile(
    r"(?:不要|别|不买|不做|排除|避免|不想|剔除|去掉)\s*(?:推荐|买入|买|持有|配置|关注|考虑|投)?\s*([^，。；!?！？\s]{1,12})"
)
_NEGATION_EXCEPT_RE = re.compile(r"除了([^，。；!?！？\s]{1,12}?)(?:以外|之外)")
_THEME_NOISE = ("帮我", "给我", "请", "哪些", "什么", "股票", "个股", "推荐", "看看", "分析")


def _codes_from_text(message: str) -> List[str]:
    """提取消息中的 A 股 6 位代码。"""
    if not message:
        return []
    return list(dict.fromkeys(_VALID_CODE_RE.findall(message)))


# ── 各意图的槽位 schema ─────────────────────────────────────────────────────────
_INTENT_SLOT_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "stock_analysis": {
        "title": "行情/个股分析",
        "slots": [
            {"key": _SLOT_NAMES, "type": "name_list", "required": False,
             "desc": "用户提到的A股股票名称（如 贵州茅台），名称将映射为代码"},
            {"key": _SLOT_CODES, "type": "code_list", "required": True,
             "desc": "需要分析的A股6位代码，如 600519"},
            {"key": "analysis_type", "type": "choice", "options": ["fundamental", "technical", "both"],
             "required": False, "default": "both",
             "desc": "分析维度：基本面 / 技术面 / 两者"},
            {"key": _SLOT_EXCLUDED, "type": "name_list", "required": False,
             "desc": "用户明确排除/否定的股票名称"},
        ],
    },
    "stock_recommendation": {
        "title": "选股/推荐",
        "slots": [
            {"key": _SLOT_THEMES, "type": "keyword_list", "required": False,
             "desc": "主题/行业/板块偏好（如 白酒、新能源、AI）"},
            {"key": _SLOT_NAMES, "type": "name_list", "required": False,
             "desc": "用户明确点名的股票名称"},
            {"key": _SLOT_CODES, "type": "code_list", "required": False,
             "desc": "用户明确给出/点名的股票代码"},
            {"key": _SLOT_EXCLUDED, "type": "name_list", "required": False,
             "desc": "用户排除/否定的股票或板块"},
            {"key": "limit", "type": "number", "required": False, "default": 5,
             "desc": "期望推荐数量"},
        ],
    },
    "asset_allocation": {
        "title": "资产配置",
        "slots": [
            {"key": _SLOT_CODES, "type": "code_list", "required": False,
             "desc": "配置标的股票代码"},
            {"key": "budget_amount", "type": "number", "required": False,
             "desc": "预算金额（元），如 10万=100000"},
            {"key": "risk_preference", "type": "text", "required": False,
             "desc": "风险偏好，如 稳健/保守/进取/激进"},
            {"key": "holding_period", "type": "text", "required": False,
             "desc": "持有期限，如 1年/6个月/3个月"},
        ],
    },
    "product_analysis": {
        "title": "产品解读",
        "slots": [
            {"key": "product_names", "type": "text_list", "required": False,
             "desc": "用户想了解/对比的金融产品名称"},
        ],
    },
    "market_insight": {"title": "市场洞察", "slots": []},
    "casual_chat": {"title": "闲聊", "slots": []},
}

# DeepSeek 抽取提示词（结构化 JSON 输出）。
# 注意：ChatPromptTemplate 用 {} 作占位符，JSON 字面量示例的括号需写成 {{ }}。
_EXTRACTION_PROMPT = """你是金融投顾的"槽位提取器"。只做字段抽取/更新，不完成业务，
结合当前消息、近期对话摘要、已有槽位，为指定意图抽取结构化入参，产出 JSON。

## 意图
{intent_title}（{intent}）

## 槽位 schema（key 与类型）
{schema_json}

## 当前输入
当前消息：{message}
近期对话摘要：{context}
已有槽位（多轮，需合并/更新，可为空）：{prior_slots}

## 抽取规则
1. 只能输出 schema 中出现的 key，缺失项省略，不要新增字段。
2. 严格用 schema 声明的类型：code_list/name_list/keyword_list/text_list 输出字符串列表；
   number 输出数字；choice 只能取 options 之一；text 输出字符串。
3. **名称与代码分离**：股票名称（如"贵州茅台"）放入 stock_names；6位代码放入 stock_codes，
   名称不要放进代码字段，反之亦然。
4. **否定表达**：识别"不要/别/不/除了…以外/排除/避免/不想/换成别的"等否定语，把被否定对象
   放入 negatives（形如 {{"stock_names": ["贵州茅台"], "themes": ["白酒"]}}），不要放进正向 slot。
5. **多轮合并**：参考已有槽位；本轮仅当用户明确补充/修改/否定时才更新对应字段，其余沿用旧值；
   用户否定某字段时，在 cleared 数组列出该字段名。
6. **歧义**：无法从消息唯一判断（如同一名称对应多只股票）时在 ambiguity 数组给出简短说明；
   无法确定时不要强行填值。
7. 只输出 JSON 对象：{{"slots": {{...}}, "negatives": {{...}}, "cleared": [...],
   "ambiguity": [...], "missing": [...]}}。"""


def _as_text_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in re.split(r"[，,、;；\n]", text) if part.strip()]


def _as_code_list(value: Any) -> List[str]:
    return [v for v in _as_text_list(value) if _VALID_CODE_RE.fullmatch(v)]


def _as_number(value: Any, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _choice(value: Any, options: List[Any], default: Any) -> Any:
    return value if value in options else default


def _normalize_raw(raw: Dict[str, Any]) -> Dict[str, Any]:
    """把 LLM 返回 dict 归一化为可信类型。"""
    slots = dict(raw.get("slots") or {}) if isinstance(raw, dict) else {}
    negatives = dict(raw.get("negatives") or {}) if isinstance(raw, dict) else {}
    return {
        "slots": slots,
        "negatives": negatives,
        "cleared": _as_text_list(raw.get("cleared")),
        "ambiguity": _as_text_list(raw.get("ambiguity")),
        "missing": _as_text_list(raw.get("missing")),
    }


# ── 名称→代码 映射 ──────────────────────────────────────────────────────────────
class _StockIndex:
    """按需加载全量股票表（一次调用），供名称→代码映射使用。"""

    def __init__(self) -> None:
        self._by_name: Dict[str, Dict[str, str]] = {}
        self._code_to_name: Dict[str, str] = {}
        self._loaded = False

    def _ensure(self) -> None:
        if self._loaded:
            return
        try:
            records = _records(get_provider_manager().get_stock_basic())
        except Exception as exc:  # noqa: BLE001
            # 失败不置 loaded，允许下次重试
            logger.warning("股票名称表加载失败：%s", exc)
            return
        for item in records:
            name = str(_first_value(item, "name", "名称", default="")).strip()
            code = str(_first_value(item, "ts_code", "code", default="")).split(".")[0].strip()
            industry = str(_first_value(item, "industry", "行业", default="")).strip()
            if not name or not code:
                continue
            self._by_name.setdefault(name, {"code": code, "industry": industry})
            self._code_to_name.setdefault(code, name)
        self._loaded = True

    def lookup(self, raw_name: str) -> Tuple[Optional[Dict[str, str]], List[Dict[str, str]]]:
        """返回 (唯一命中, 歧义候选列表)。

        优先级：精确名称 → 常用别名 → 名称子串（唯一则命中，多个则视为歧义）。
        """
        self._ensure()
        name = (raw_name or "").strip()
        if not name:
            return None, []

        if name in self._by_name:
            return self._by_name[name], []

        alias_code = _STOCK_ALIASES.get(name)
        if alias_code:
            return {"code": alias_code, "industry": self._by_name.get(name, {}).get("industry", "")}, []

        matches = [item for key, item in self._by_name.items() if name in key]
        if len(matches) == 1:
            return matches[0], []
        if len(matches) > 1:
            codes = {m["code"] for m in matches}
            if len(codes) == 1:
                return matches[0], []
            return None, [
                {"name": key, "code": item["code"]}
                for key, item in self._by_name.items()
                if name in key
            ]
        return None, []

    def name_for_code(self, code: str) -> str:
        self._ensure()
        return self._code_to_name.get(code, "")

    @property
    def names(self) -> List[str]:
        self._ensure()
        return list(self._by_name.keys())


_INDEX = _StockIndex()


def reset_stock_index() -> None:
    """测试用：重置股票名称表缓存，迫使下次按数据源重新加载。"""
    _INDEX._loaded = False
    _INDEX._by_name = {}
    _INDEX._code_to_name = {}


def _map_stock_names(names: List[str]) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """把名称列表映射为 [{code, name}]；返回 (已解析, 歧义项列表)。"""
    resolved: List[Dict[str, str]] = []
    ambiguous: List[Dict[str, str]] = []
    seen: set = set()
    for raw in names:
        key = (raw or "").strip()
        if not key:
            continue
        hit, ambs = _INDEX.lookup(key)
        if hit:
            code = hit["code"]
            if code not in seen:
                seen.add(code)
                resolved.append({"code": code, "name": key})
        elif ambs:
            candidates = "、".join(f"{a['name']}({a['code']})" for a in ambs)
            ambiguous.append({"name": key, "candidates": candidates})
    return resolved, ambiguous


# ── 确定性抽取（LLM 不可用时的兜底） ────────────────────────────────────────────
def _strip_theme_noise(text: str) -> str:
    for token in _THEME_NOISE:
        text = text.replace(token, "")
    parts = re.split(r"[，,、;；。\n]", text)
    out = []
    for part in parts:
        p = part.strip()
        if not p or re.search(r"(不要|别|不买|不做|排除|避免|不想|剔除|去掉|除了)", p):
            continue
        out.append(p)
    return " ".join([p for p in out if len(p) > 1])


def _candidate_names(message: str) -> List[str]:
    """从消息中找全量股票名称表里出现的名称（最长优先、子串去重）。"""
    corpus = _INDEX.names
    if not corpus:
        return []
    found = []
    for name in corpus:
        idx = message.find(name)
        if idx >= 0:
            found.append((idx, name))
    found.sort(key=lambda t: (-len(t[1]), t[0]))
    chosen: List[str] = []
    spans: List[Tuple[int, int]] = []
    for idx, name in found:
        start, end = idx, idx + len(name)
        if any(start >= s and end <= e for s, e in spans):
            continue
        spans.append((start, end))
        chosen.append(name)
    return chosen[:5]


def _extract_amount(message: str) -> Optional[float]:
    m = re.search(r"(\d+(?:\.\d+)?)\s*万", message)
    if m:
        return float(m.group(1)) * 10000
    m = re.search(r"(\d+(?:\.\d+)?)\s*元", message)
    if m and float(m.group(1)) >= 100:
        return float(m.group(1))
    return None


_RISK_LEVELS = (
    ("R5 高风险", ("高风险", "进取", "激进")),
    ("R4 中高风险", ("中高风险", "积极")),
    ("R3 中风险", ("中风险", "平衡")),
    ("R2 中低风险", ("中低风险", "稳健")),
    ("R1 低风险", ("低风险", "保守")),
)


def _extract_risk(message: str) -> Optional[str]:
    for level, words in _RISK_LEVELS:
        if any(word in message for word in words):
            return level
    return None


def _extract_horizon(message: str) -> Optional[str]:
    m = re.search(r"(\d+)\s*(天|周|个月|月|年)", message)
    return "".join(m.groups()) if m else None


def _extract_negated_names(message: str) -> List[str]:
    out: List[str] = []
    for match in _NEGATION_RE.finditer(message):
        target = (match.group(1) or "").strip()
        if target and len(target) > 1 and target not in out:
            out.append(target)
    for match in _NEGATION_EXCEPT_RE.finditer(message):
        target = (match.group(1) or "").strip()
        if target and len(target) > 1 and target not in out:
            out.append(target)
    return out


def _candidate_product_names(message: str) -> List[str]:
    if not message:
        return []
    parts = re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]{2,12}(?:基金|ETF|债基|指数|产品)", message)
    return list(dict.fromkeys(parts))[:5]


def _deterministic_extract(message: str, intent: str) -> Dict[str, Any]:
    """不依赖 LLM 的确定性槽位抽取（覆盖代码/名称/否定/预算/风险/期限）。"""
    slots: Dict[str, Any] = {}
    codes = _codes_from_text(message)
    excluded = _extract_negated_names(message)

    if intent == "stock_analysis":
        if codes:
            slots[_SLOT_CODES] = codes
        else:
            names = _candidate_names(message)
            if names:
                slots[_SLOT_NAMES] = names
        if excluded:
            slots[_SLOT_EXCLUDED] = excluded
    elif intent == "stock_recommendation":
        slots[_SLOT_CODES] = codes
        themes = _strip_theme_noise(message)
        if themes and len(themes) > 1:
            slots[_SLOT_THEMES] = _as_text_list(themes)[:5]
        if excluded:
            slots[_SLOT_EXCLUDED] = excluded
    elif intent == "asset_allocation":
        slots[_SLOT_CODES] = codes
        amount = _extract_amount(message)
        if amount is not None:
            slots["budget_amount"] = amount
        risk = _extract_risk(message)
        if risk:
            slots["risk_preference"] = risk
        horizon = _extract_horizon(message)
        if horizon:
            slots["holding_period"] = horizon
    elif intent == "product_analysis":
        products = _candidate_product_names(message)
        if products:
            slots["product_names"] = products

    return _normalize_raw({"slots": slots, "negatives": {}, "cleared": [], "ambiguity": [], "missing": []})


# ── 合并与解析 ──────────────────────────────────────────────────────────────────
def _merge_slots(prior: Dict[str, Any], raw: Dict[str, Any]) -> Dict[str, Any]:
    """把本轮 raw 合并进 prior（多轮合并/更新）。

    - 保留 prior 中未被本轮覆盖/清除的字段；
    - 本轮显式给出值则覆盖；
    - cleared 中列出的字段从结果中移除；
    - negatives 中的字段并入对应字段（excluded 语义由调用方解释）。
    """
    cleared = set(_as_text_list(raw.get("cleared")))
    merged: Dict[str, Any] = dict(prior or {})
    for key in cleared:
        merged.pop(key, None)
    for key, val in (raw.get("slots") or {}).items():
        if val in (None, "", [], {}):
            continue
        merged[key] = val
    negatives = raw.get("negatives") or {}
    if isinstance(negatives, dict):
        for key, vals in negatives.items():
            items = _as_text_list(vals)
            if not items:
                continue
            current = _as_text_list(merged.get(key))
            merged[key] = list(dict.fromkeys(current + items))
    return merged


def _resolve_slots(intent: str, raw: Dict[str, Any], prior: Dict[str, Any]) -> Dict[str, Any]:
    """合并并解析出一个意图的最终槽位：名称→代码、排除项、默认值。

    返回 dict 除各槽位字段外，还含：
    - ``_excluded_codes``：排除的代码列表
    - ``_resolved``：解析出的 [{code, name}]（供写回 resolved_stocks）
    - ``_ambiguity``：歧义项列表 [{name, candidates}]
    - ``_required_missing``：必填槽位缺失标记（当前仅 stock_analysis 的代码）
    """
    merged = _merge_slots(prior, raw)

    excluded_names = _as_text_list(merged.get(_SLOT_EXCLUDED))
    excluded_codes = _codes_from_text(" ".join(excluded_names))
    for raw_name in excluded_names:
        if _VALID_CODE_RE.fullmatch(raw_name):
            continue  # 已是代码
        hit, _ = _INDEX.lookup(raw_name)
        if hit and hit["code"] not in excluded_codes:
            excluded_codes.append(hit["code"])

    names = _as_text_list(merged.get(_SLOT_NAMES))
    mapped, ambiguous = _map_stock_names(names)
    codes = _as_code_list(merged.get(_SLOT_CODES))
    resolved_entries: List[Dict[str, str]] = []
    for entry in mapped:
        if entry["code"] not in codes and entry["code"] not in excluded_codes:
            codes.append(entry["code"])
    for code in codes:
        if code not in excluded_codes:
            resolved_entries.append({"code": code, "name": _INDEX.name_for_code(code)})
    codes = [c for c in codes if c not in excluded_codes]
    seen: set = set()
    resolved_entries = [e for e in resolved_entries if e["code"] not in seen and not seen.add(e["code"])][:10]

    result: Dict[str, Any] = {
        _SLOT_CODES: codes[:10],
        _SLOT_EXCLUDED: excluded_codes or excluded_names or [],
        "_excluded_codes": excluded_codes,
        "_resolved": resolved_entries,
        "_ambiguity": ambiguous,
    }
    if intent in {"stock_analysis", "stock_recommendation"} and _as_text_list(merged.get(_SLOT_NAMES)):
        result[_SLOT_NAMES] = _as_text_list(merged.get(_SLOT_NAMES))
    if intent == "stock_analysis":
        result["analysis_type"] = _choice(merged.get("analysis_type"), ["fundamental", "technical", "both"], "both")
        result["_required_missing"] = bool(not codes and not names)
    elif intent == "stock_recommendation":
        themes = _as_text_list(merged.get(_SLOT_THEMES))
        if themes:
            result[_SLOT_THEMES] = themes
        result["limit"] = int(_as_number(merged.get("limit"), 5) or 5)
    elif intent == "asset_allocation":
        for field in ("budget_amount", "risk_preference", "holding_period"):
            if merged.get(field) not in (None, ""):
                result[field] = merged[field]
    elif intent == "product_analysis":
        result["product_names"] = _as_text_list(merged.get("product_names"))

    return result


def _schema_json(schema: Dict[str, Any]) -> str:
    out = []
    for s in schema.get("slots", []):
        extra = []
        if s.get("required"):
            extra.append("必填")
        if s.get("options"):
            extra.append("可选值：" + "/".join(str(o) for o in s["options"]))
        if s.get("default") is not None:
            extra.append(f"默认 {s['default']}")
        line = f"- {s['key']}（{s['type']}）：{s.get('desc', '')}"
        if extra:
            line += "；" + "；".join(extra)
        out.append(line)
    return "\n".join(out) or "（无）"


class SlotExtractor:
    """意图后置槽位提取器，抽取 + 名称→代码 + 否定/歧义/多轮合并。"""

    def __init__(self, model: Any = None) -> None:
        self._model = model
        self._chain = None

    @property
    def model(self) -> Any:
        if self._model is None:
            self._model = get_model_for_agent("slot_extraction")
        return self._model

    @property
    def chain(self) -> Any:
        if self._chain is None:
            prompt = ChatPromptTemplate.from_messages([("system", _EXTRACTION_PROMPT)])
            self._chain = prompt | self.model | StrOutputParser()
        return self._chain

    def _llm_extract(
        self, message: str, intent: str, schema: Dict[str, Any], prior: Dict[str, Any], context: str,
    ) -> Dict[str, Any]:
        raw_text = self.chain.invoke({
            "intent": intent,
            "intent_title": schema.get("title", intent),
            "schema_json": _schema_json(schema),
            "message": message,
            "context": context,
            "prior_slots": json.dumps(prior, ensure_ascii=False),
        })
        parsed = safe_parse_json(raw_text, {})
        return _normalize_raw(parsed) if isinstance(parsed, dict) else _normalize_raw({})

    def _extract_one(
        self, message: str, intent: str, schema: Dict[str, Any], prior: Dict[str, Any], context: str,
    ) -> Dict[str, Any]:
        try:
            return self._llm_extract(message, intent, schema, prior, context)
        except Exception as exc:  # noqa: BLE001
            logger.warning("槽位 LLM 抽取失败，回退确定性抽取 intent=%s err=%s", intent, exc)
            return _deterministic_extract(message, intent)

    def extract(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """入口：读取用户消息/摘要/已派单/既有槽位，产出并写回槽位与解析结果。"""
        message = str(state.get("user_message", "") or state.get("requirement", ""))
        context = str(state.get("memory_context", ""))
        prior = dict(state.get("intent_slots", {}) or {})
        dispatch = list(state.get("task_dispatch", []) or [])

        slots_by_intent: Dict[str, Dict[str, Any]] = {}
        resolved_stocks: List[Dict[str, Any]] = []
        explicit_codes: List[str] = _codes_from_text(message)
        profile_from_slots: Dict[str, Any] = {}
        clarification: List[str] = []
        pruned_intents: List[str] = []

        for item in dispatch:
            intent = str(item.get("intent", "")).strip()
            schema = _INTENT_SLOT_SCHEMAS.get(intent)
            if not schema or not schema.get("slots"):
                continue
            raw = self._extract_one(message, intent, schema, prior.get(intent, {}), context)
            resolved = _resolve_slots(intent, raw, prior.get(intent, {}))
            slots_by_intent[intent] = resolved

            codes = _as_code_list(resolved.get(_SLOT_CODES))
            _excluded_codes = resolved.get("_excluded_codes") or []
            entries = resolved.get("_resolved") or []
            ambigs = resolved.get("_ambiguity") or []

            if intent in {"stock_analysis", "stock_recommendation"}:
                for entry in entries:
                    if entry["code"] not in _excluded_codes and entry["code"] not in [
                        r["code"] for r in resolved_stocks
                    ]:
                        resolved_stocks.append(entry)
                if intent == "stock_analysis" and resolved.get("_required_missing"):
                    # 个股分析必须提供标的；市场概览已独立为 market_insight，不走此意图。
                    pruned_intents.append(intent)
                    clarification.append("请提供需要分析的股票名称或6位代码。")
                for a in ambigs:
                    candidates = a.get("candidates", "多个标的")
                    clarification.append(
                        f"您提到的「{a.get('name', '')}」可能指{candidates}，请确认具体标的。"
                    )
            elif intent == "asset_allocation":
                for entry in entries:
                    if entry["code"] not in profile_from_slots.get("stock_codes", []):
                        profile_from_slots.setdefault("stock_codes", []).append(entry["code"])
                for field in ("budget_amount", "risk_preference", "holding_period"):
                    if resolved.get(field) not in (None, ""):
                        profile_from_slots[field] = resolved[field]
            elif intent == "product_analysis":
                slots_by_intent[intent]["product_names"] = _as_text_list(resolved.get("product_names"))

        state["intent_slots"] = slots_by_intent
        if resolved_stocks:
            state["resolved_stocks"] = resolved_stocks[:10]
        if explicit_codes:
            state["explicit_user_stock_codes"] = list(dict.fromkeys(explicit_codes))

        # 资产配置：抽取后仅填充画像缺失字段（不覆盖已确认画像）
        if profile_from_slots:
            profile = dict(state.get("user_profile", {}) or {})
            for key, value in profile_from_slots.items():
                if not profile.get(key):
                    profile[key] = value
            state["user_profile"] = profile

        if clarification:
            existing = str(state.get("clarification_question", "")).strip()
            all_q = [q for q in dict.fromkeys([existing, *clarification]) if q]
            state["clarification_question"] = "；".join(all_q)
        if pruned_intents:
            state["task_dispatch"] = [
                item for item in dispatch if str(item.get("intent", "")).strip() not in pruned_intents
            ]
            kept_ids = {
                str(item.get("task_id", ""))
                for item in state["task_dispatch"]
                if item.get("task_id")
            }
            if state.get("tasks"):
                state["tasks"] = [
                    task for task in state["tasks"]
                    if (
                        task.task_id in kept_ids
                        if kept_ids
                        else task.intent.value not in pruned_intents
                    )
                ]
                kept_task_ids = {task.task_id for task in state["tasks"]}
                for task in state["tasks"]:
                    task.depends_on = [
                        dependency for dependency in task.depends_on
                        if dependency in kept_task_ids
                    ]
            state["task_plan"] = list(dict.fromkeys(
                str(item.get("expert", ""))
                for item in state["task_dispatch"]
                if item.get("expert")
            ))

        return state


__all__ = ["SlotExtractor", "reset_stock_index"]
