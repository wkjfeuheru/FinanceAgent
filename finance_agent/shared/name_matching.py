"""专有名称的分级匹配：全称 / 简称（后缀省略）/ 近似（错别字）。

用户常用**缩写**指代标的：股票说"茅台"（全称"贵州茅台"）、基金说"易方达中小盘"
（全称"易方达中小盘混合"），偶尔还会写错一两个字。旧的名称→代码解析只做
"官方全称逐字出现在消息里"的单向子串判断，缩写与错字一律落空。

本模块把这层判断抽成**纯函数**（无 IO、无第三方依赖，仅标准库 ``difflib``），
按证据强度分档：

- ``3`` 精确：官方全称逐字出现在消息中（保持既有语义，支持多标的比较）；
- ``2`` 简称：去噪后的查询词是全称的**连续子串**（如"茅台"⊂"贵州茅台"）；
- ``1`` 近似：序列相似度达到阈值（容忍错别字）。

命中多个不同代码时**不猜**：调用方据此触发澄清，与产品域
``ProductReferenceResolver`` 的既有立场一致。
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Iterable, Sequence

#: 简称匹配的最小长度：单字过于宽泛（"中"会命中上百只），不作为缩写。
_MIN_ABBREV_LEN = 2
#: 标准近似阈值与允许的长度差（长度差过大视为不同名）。
_FUZZY_RATIO = 0.8
_FUZZY_LEN_DELTA = 2
#: 短名（≥4 字）错一字的宽松阈值：4 字名错 1 字 ratio 只有 0.75，
#: 但要求存在 ≥2 字的公共块，避免只共享一个字也被判为近似。
_FUZZY_LOOSE_RATIO = 0.7
_FUZZY_MIN_LEN = 4
_FUZZY_MIN_BLOCK = 2
#: 澄清文案里最多列举的候选数。
_MAX_CANDIDATES = 5

#: 请求噪声短语：中文无分词，用户措辞会与名称粘连，须先剔除再取候选词。
#: 长词在前替换，避免短词先命中把长词截断。
_QUERY_NOISE = (
    "帮我看看", "帮我推荐", "帮我查查", "帮我分析", "帮我研究", "帮我",
    "给我推荐", "给我看看", "给我", "麻烦您", "麻烦你", "请帮我", "请分析",
    "请对比", "请研究", "请问", "请",
    "我想了解", "我想知道", "我想研究", "我想", "我要", "想看看",
    "分析一下", "对比一下", "比较一下", "了解一下", "看一下", "查一下", "研究一下",
    "怎么样", "如何看", "如何", "值得投资吗", "值得买吗", "值得关注吗",
    "值得投资", "值得关注", "值得买", "能买吗", "可以买吗",
    "有哪些", "有什么", "哪些", "什么", "几只", "几个", "几支", "几档",
    "一些", "一只", "一支", "一下", "一点",
    "看看", "了解", "分析", "对比", "比较", "研究", "推荐", "筛选",
    "股票", "个股", "标的", "板块", "行业", "概念", "龙头", "题材", "主题",
    "走势", "行情", "基本面", "技术面", "财务面", "估值", "财务",
    "最近", "近期", "现在", "今天", "目前",
    "投资机会", "投资价值", "投资", "机会", "情况", "表现", "介绍",
)
#: 连接词与标点：替换为空格以切分多个名称（"茅台和五粮液"→"茅台 五粮液"）。
_SEPARATORS = (
    "和", "与", "及", "跟", "同", "、", "，", ",", "。", "；", ";", "：", ":",
    "？", "?", "！", "!", "的", "了", "吧", "呢", "吗", "啊",
)
#: 通用金融词：作为独立查询词时过于宽泛，不足以唯一指代标的，跳过简称匹配。
_GENERIC_TOKENS = frozenset({
    "中国", "证券", "银行", "基金", "股票", "指数", "板块", "行业", "概念",
    "龙头", "主题", "股份", "集团", "控股", "科技", "投资", "资产", "公司",
    "市场", "理财", "产品", "etf", "沪深", "上证", "深证", "中证",
})


def _fold(text: Any) -> str:
    """NFKC 归一化 + 大小写折叠（保留空白，供分词）。"""
    return unicodedata.normalize("NFKC", str(text or "")).casefold()


def normalise(text: Any) -> str:
    """归一化名称/查询：NFKC + 大小写折叠 + 去空白。"""
    return "".join(_fold(text).split())


@dataclass(frozen=True)
class PreparedQuery:
    """一次查询的预处理结果：归一化整串 + 去噪分词（供批量候选复用）。"""

    normalised: str
    tokens: tuple[str, ...]


@dataclass(frozen=True)
class Candidate:
    """一个名称候选及其命中档位。"""

    code: str
    name: str
    tier: int
    score: float


@dataclass
class NameMatch:
    """名称匹配结果：唯一代码、歧义候选或空。"""

    codes: list[str] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)
    ambiguous_tokens: list[str] = field(default_factory=list)

    @property
    def ambiguous(self) -> bool:
        return bool(self.ambiguous_tokens)


def prepare_query(message: Any) -> PreparedQuery:
    """归一化并切分查询：剔除请求噪声与连接词，保留 ≥2 字的候选词。"""
    text = _fold(message)
    for phrase in sorted(_QUERY_NOISE, key=len, reverse=True):
        text = text.replace(_fold(phrase), " ")
    for sep in _SEPARATORS:
        text = text.replace(_fold(sep), " ")
    tokens = [token for token in text.split() if len(token) >= _MIN_ABBREV_LEN]
    return PreparedQuery(normalised=normalise(message), tokens=tuple(dict.fromkeys(tokens)))


def _longest_block(left: str, right: str) -> int:
    matcher = SequenceMatcher(None, left, right)
    return max((block.size for block in matcher.get_matching_blocks()), default=0)


def _token_tier(token: str, name: str) -> tuple[int, float]:
    """单个查询词对一个官方名称的命中档位。"""
    if not token or not name:
        return (0, 0.0)
    if token == name:
        return (3, 1.0)
    if token not in _GENERIC_TOKENS and token in name:
        return (2, len(token) / len(name))
    ratio = SequenceMatcher(None, token, name).ratio()
    if ratio >= _FUZZY_RATIO and abs(len(token) - len(name)) <= _FUZZY_LEN_DELTA:
        return (1, ratio)
    if (
        min(len(token), len(name)) >= _FUZZY_MIN_LEN
        and ratio >= _FUZZY_LOOSE_RATIO
        and _longest_block(token, name) >= _FUZZY_MIN_BLOCK
    ):
        return (1, ratio)
    return (0, 0.0)


def tier_of(query: PreparedQuery, name: Any) -> tuple[int, float]:
    """查询对一个名称的命中档位：先判全称逐字出现，再按查询词取最高档。"""
    normalised_name = normalise(name)
    if not normalised_name:
        return (0, 0.0)
    if normalised_name in query.normalised:
        return (3, 1.0)
    best: tuple[int, float] = (0, 0.0)
    for token in query.tokens:
        tier, score = _token_tier(token, normalised_name)
        if tier > best[0] or (tier == best[0] and tier and score > best[1]):
            best = (tier, score)
    return best


def match_names(
    message: Any,
    items: Iterable[dict[str, Any]],
    *,
    code_key: str = "code",
    name_key: str = "name",
    max_codes: int = _MAX_CANDIDATES,
) -> NameMatch:
    """把消息中的名称解析为代码；命中多个不同代码时记为歧义。

    ``items`` 是候选集（每个含代码与名称）。规则：
    1. 官方全称逐字出现在消息中 → 直接命中（支持多标的比较）；
    2. 其余按查询词匹配（全称/简称/近似），某词命中多个不同代码 → 记入歧义；
    3. 两条路径的结果合并去重；无任何命中 → 空结果。
    """
    rows: list[tuple[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        code = str(item.get(code_key, "") or "").strip()
        name = str(item.get(name_key, "") or "").strip()
        if code and name:
            rows.append((code, name))
    if not rows:
        return NameMatch()

    query = prepare_query(message)
    resolved: list[str] = []
    ambiguous_tokens: list[str] = []
    matched: list[Candidate] = []

    # 路径一：官方全称逐字出现在整条消息里（保持既有"全称命中"的强语义）。
    for code, name in rows:
        if normalise(name) in query.normalised:
            if code not in resolved:
                resolved.append(code)
            matched.append(Candidate(code, name, 3, 1.0))

    # 路径二：按查询词做分级匹配，逐词判定唯一或歧义。
    for token in query.tokens:
        scored = [
            Candidate(code, name, *_token_tier(token, normalise(name)))
            for code, name in rows
        ]
        scored = [candidate for candidate in scored if candidate.tier > 0]
        if not scored:
            continue
        best_tier = max(candidate.tier for candidate in scored)
        top = [candidate for candidate in scored if candidate.tier == best_tier]
        deduped: dict[str, Candidate] = {}
        for candidate in top:
            deduped.setdefault(candidate.code, candidate)
        top = list(deduped.values())
        for candidate in top:
            if candidate not in matched:
                matched.append(candidate)
        if len(top) == 1:
            if top[0].code not in resolved:
                resolved.append(top[0].code)
        else:
            ambiguous_tokens.append(token)

    matched.sort(key=lambda candidate: (-candidate.tier, -candidate.score))
    return NameMatch(
        codes=resolved[:max_codes],
        candidates=matched[:max_codes],
        ambiguous_tokens=ambiguous_tokens,
    )


def strip_type_suffix(name: Any, suffixes: Sequence[str]) -> str:
    """去掉名称尾部的类型词（"易方达中小盘混合"→"易方达中小盘"）。

    仅当去掉后仍有内容时才生效，避免把"基金"这类纯类型词削成空串。
    """
    text = str(name or "").strip()
    for suffix in sorted(suffixes, key=len, reverse=True):
        if suffix and text.endswith(suffix) and len(text) > len(suffix):
            return text[: -len(suffix)].strip()
    return text


def unclear_text(label: str, candidates: Sequence[Candidate], *, code_hint: str = "6 位代码") -> str:
    """歧义澄清文案：列出候选（名称+代码）并请用户补充更精确的指代。"""
    listed = "、".join(f"{candidate.name}（{candidate.code}）" for candidate in candidates[:_MAX_CANDIDATES])
    return (
        f"「{label}」可能指多个标的：{listed}。"
        f"请补充{code_hint}或更完整的名称，以便准确分析。"
    )


__all__ = [
    "Candidate",
    "NameMatch",
    "PreparedQuery",
    "match_names",
    "normalise",
    "prepare_query",
    "strip_type_suffix",
    "tier_of",
    "unclear_text",
]
