"""资产配置测算工具（纯函数，零外部依赖）。

只做数学，不做交易：函数接收标量列表/持仓字典，返回 dict，仅依赖 ``math`` 与
``statistics``，风格与 ``orchestrator/tools/technical.py`` 一致。账户领域用本模块
把"我的持仓"转成配置诊断与测算参考；模块本身不写库、不调模型、不下单。

**单位约定**（与产品库 ``finance.product_performance`` 一致，全部为十进制小数）：
收益率与波动率 ``0.126`` 表示 12.6%，最大回撤 ``0.187`` 表示回撤 18.7%，权重为
``0..1`` 的小数。注意 ``PositionView.weight`` 是百分数（0..100），调用方需先 ÷100。

**数据口径与已知局限**：仓库没有产品净值时间序列——``finance.product_performance``
每个产品只有一行快照，且产品间 ``update_date`` 并不对齐，因此**无法**得到真实的
协方差/相关矩阵。所有需要相关性的函数在 ``correlations=None`` 时采用**对角
（零相关）近似**并在返回值里标注 ``approximation="zero_correlation"``；``correlations``
参数已预留，待净值时序就位即可切到完整口径，调用方无需改动。

**合规**：所有措辞限于"测算/参考/区间"，不输出买卖或调仓指令，因此可原样通过
现有合规出口（``middleware/content_filter.py`` + ``orchestrator/compliance.py``）。
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping, Sequence

# ── 风险分档 ─────────────────────────────────────────────────────
# 产品库只有自由文本 risk_level（如 "R3 中风险"），且无资产大类字段；因此按风险
# 等级归并为低/中/高三档，作为配置诊断的桶。R1-R2 低、R3 中、R4-R5 高。
TIER_LOW = "低风险"
TIER_MID = "中风险"
TIER_HIGH = "高风险"
TIER_UNKNOWN = "未分类"

_TIER_KEYS: tuple[str, ...] = (TIER_LOW, TIER_MID, TIER_HIGH)
_TIER_BY_RISK: dict[str, str] = {
    "R1": TIER_LOW, "R2": TIER_LOW,
    "R3": TIER_MID,
    "R4": TIER_HIGH, "R5": TIER_HIGH,
}

#: 三档参考区间（占比小数）。**固定的演示用参考模型**，不是个性化建议，也不构成
#: 投资建议；仅用于展示"当前配置与风险偏好是否偏离"，措辞统一为"参考区间"。
REFERENCE_BANDS: dict[str, dict[str, tuple[float, float]]] = {
    "R1": {TIER_LOW: (0.70, 0.90), TIER_MID: (0.10, 0.25), TIER_HIGH: (0.00, 0.05)},
    "R2": {TIER_LOW: (0.55, 0.75), TIER_MID: (0.20, 0.35), TIER_HIGH: (0.05, 0.15)},
    "R3": {TIER_LOW: (0.35, 0.55), TIER_MID: (0.25, 0.45), TIER_HIGH: (0.15, 0.30)},
    "R4": {TIER_LOW: (0.20, 0.35), TIER_MID: (0.25, 0.45), TIER_HIGH: (0.30, 0.45)},
    "R5": {TIER_LOW: (0.05, 0.20), TIER_MID: (0.20, 0.40), TIER_HIGH: (0.45, 0.65)},
}

#: 未提供风险偏好时使用的口径标签（不参与区间对比）。
_GENERIC_BASIS = "generic"


# ── 基础工具 ─────────────────────────────────────────────────────


def _finite(value: Any) -> float | None:
    """转成有限浮点；None/非数/NaN/Inf 一律返回 None（不抛异常）。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _as_floats(values: Iterable[Any]) -> list[float | None]:
    return [_finite(value) for value in values]


def normalize_weights(weights: Sequence[Any]) -> list[float]:
    """把权重归一到和为 1；负数与非法值按 0 处理。全零时退化为等权。"""
    cleaned: list[float] = []
    for item in weights:
        value = _finite(item)
        cleaned.append(max(0.0, value) if value is not None else 0.0)
    total = sum(cleaned)
    if total <= 0 or not math.isfinite(total):
        return equal_weight(len(cleaned))
    return [value / total for value in cleaned]


def equal_weight(count: int) -> list[float]:
    """等权：n 个资产各 1/n；n<=0 返回空列表。"""
    if count <= 0:
        return []
    share = 1.0 / count
    return [share] * count


def inverse_volatility_weights(volatilities: Sequence[Any]) -> list[float]:
    """逆波动率权重（1/σ 归一）。缺失或非正波动率按 0 处理。

    对角（零相关）假设下，逆波动率即风险平价解，因此本函数也是
    ``risk_budget_weights`` 的默认实现。
    """
    raw: list[float] = []
    for item in volatilities:
        vol = _finite(item)
        raw.append(1.0 / vol if vol is not None and vol > 0 else 0.0)
    return normalize_weights(raw)


def risk_budget_weights(
    volatilities: Sequence[Any],
    budgets: Sequence[Any] | None = None,
) -> list[float]:
    """风险预算权重。对角线（零相关）口径下解为 ∝ 预算/σ。

    ``budgets=None`` 时各资产风险预算相同，退化为 ``inverse_volatility_weights``。
    非对角口径需要协方差矩阵，本仓库暂无净值时序，故不提供。
    """
    if budgets is None:
        return inverse_volatility_weights(volatilities)
    raw: list[float] = []
    for vol_item, budget_item in zip(volatilities, budgets):
        vol = _finite(vol_item)
        budget = _finite(budget_item)
        if vol is not None and vol > 0 and budget is not None and budget > 0:
            raw.append(budget / vol)
        else:
            raw.append(0.0)
    return normalize_weights(raw)


def constrained_weights(
    weights: Sequence[Any], weight_min: float = 0.0, weight_max: float = 1.0,
) -> list[float]:
    """在 [weight_min, weight_max] 内近似投影并归一。

    迭代"截断→归一"直到稳定；约束不可行（下限和 >1 或上限和 <1）时退回无约束
    归一，不做无限逼近——参考权重的展示精度足够。
    """
    count = len(weights)
    if count == 0:
        return []
    low = max(0.0, float(weight_min))
    high = min(1.0, float(weight_max))
    if high < low or low * count > 1.0 + 1e-12 or high * count < 1.0 - 1e-12:
        return normalize_weights(weights)
    current = normalize_weights(weights)
    for _ in range(100):
        clipped = [min(max(value, low), high) for value in current]
        total = sum(clipped)
        if total <= 0:
            return normalize_weights(weights)
        if abs(total - 1.0) < 1e-12:
            return clipped
        current = [value / total for value in clipped]
    return current


# ── 组合收益与风险 ───────────────────────────────────────────────


def portfolio_return(weights: Sequence[Any], returns: Sequence[Any]) -> float | None:
    """组合加权收益 = Σ wᵢ·rᵢ。任一权重/收益缺失时按 0 计；无有效值返回 None。"""
    total = 0.0
    seen = False
    for weight_item, return_item in zip(weights, returns):
        weight = _finite(weight_item)
        value = _finite(return_item)
        if weight is None or value is None:
            continue
        total += weight * value
        seen = True
    return total if seen else None


def portfolio_volatility(
    weights: Sequence[Any],
    volatilities: Sequence[Any],
    correlations: Sequence[Sequence[float]] | None = None,
) -> float | None:
    """组合波动率。

    ``correlations=None`` 时用对角（零相关）近似 ``sqrt(Σ (wᵢσᵢ)²)``；给出相关系数
    矩阵时用完整式 ``sqrt(ΣᵢΣⱼ wᵢwⱼσᵢσⱼρᵢⱼ)``。缺波动率的资产按 0 计入。
    """
    w = _as_floats(weights)
    s = _as_floats(volatilities)
    count = min(len(w), len(s))
    if count == 0:
        return None
    contributions = [
        0.0 if (w[i] is None or s[i] is None) else (w[i] or 0.0) * (s[i] or 0.0)
        for i in range(count)
    ]
    if not any(contributions):
        return None
    if correlations is None:
        return math.sqrt(sum(value * value for value in contributions))
    variance = 0.0
    for i in range(count):
        for j in range(count):
            rho = _correlation(correlations, i, j, count)
            if rho is None:
                rho = 1.0 if i == j else 0.0
            variance += contributions[i] * contributions[j] * rho
    if variance <= 0:
        return None
    return math.sqrt(variance)


def _correlation(
    correlations: Sequence[Sequence[float]], i: int, j: int, count: int,
) -> float | None:
    try:
        row = correlations[i]
        value = row[j]
    except (IndexError, TypeError):
        return None
    if i >= count or j >= count:
        return None
    return _finite(value)


def portfolio_sharpe(
    expected_return: float | None, volatility: float | None, risk_free: float = 0.0,
) -> float | None:
    """组合夏普 = (收益 - 无风险收益) / 波动率；波动率非正或无有效值返回 None。"""
    ret = _finite(expected_return)
    vol = _finite(volatility)
    rf = _finite(risk_free) or 0.0
    if ret is None or vol is None or vol <= 0:
        return None
    return (ret - rf) / vol


def portfolio_max_drawdown(
    weights: Sequence[Any], drawdowns: Sequence[Any],
) -> float | None:
    """加权最大回撤近似 = Σ wᵢ·|ddᵢ|。

    仅为组合层面的粗略指代（忽略各资产回撤的同时性与相关性），不是路径相关的真实
    组合回撤；返回值以正数表示回撤幅度。
    """
    total = 0.0
    seen = False
    for weight_item, dd_item in zip(weights, drawdowns):
        weight = _finite(weight_item)
        dd = _finite(dd_item)
        if weight is None or dd is None:
            continue
        total += weight * abs(dd)
        seen = True
    return total if seen else None


def diversification_ratio(
    weights: Sequence[Any],
    volatilities: Sequence[Any],
    correlations: Sequence[Sequence[float]] | None = None,
) -> float | None:
    """分散化比率 = (Σ wᵢσᵢ) / σ_p；≤1 视为无分散收益。"""
    w = _as_floats(weights)
    s = _as_floats(volatilities)
    weighted_vol = 0.0
    for weight_item, vol_item in zip(w, s):
        if weight_item is None or vol_item is None:
            continue
        weighted_vol += weight_item * vol_item
    vol = portfolio_volatility(weights, volatilities, correlations)
    if vol is None or vol <= 0 or weighted_vol <= 0:
        return None
    return weighted_vol / vol


# ── 集中度与风险贡献 ─────────────────────────────────────────────


def concentration_metrics(weights: Sequence[Any]) -> dict[str, Any]:
    """集中度指标：HHI、前 1/前 3 大占比、等效持仓数（1/HHI）。"""
    normalized = normalize_weights(weights)
    count = len(normalized)
    if count == 0:
        return {
            "position_count": 0, "hhi": None, "effective_n": None,
            "top1_weight": None, "top3_weight": None,
        }
    hhi = sum(value * value for value in normalized)
    ordered = sorted(normalized, reverse=True)
    return {
        "position_count": count,
        "hhi": round(hhi, 6),
        "effective_n": round(1.0 / hhi, 4) if hhi > 0 else None,
        "top1_weight": round(ordered[0], 6),
        "top3_weight": round(sum(ordered[:3]), 6),
    }


def risk_contribution(
    weights: Sequence[Any],
    volatilities: Sequence[Any],
    correlations: Sequence[Sequence[float]] | None = None,
) -> list[float] | None:
    """各资产对组合波动率的贡献占比（和为 1）。

    对角口径下 RCᵢ = (wᵢσᵢ)² / σ_p²；给出相关阵时 RCᵢ = wᵢ·(Σw)ᵢ / σ_p²。
    """
    w = _as_floats(weights)
    s = _as_floats(volatilities)
    count = min(len(w), len(s))
    if count == 0:
        return None
    contributions = [
        0.0 if (w[i] is None or s[i] is None) else (w[i] or 0.0) * (s[i] or 0.0)
        for i in range(count)
    ]
    variance = sum(value * value for value in contributions)
    if correlations is not None:
        variance = 0.0
        for i in range(count):
            for j in range(count):
                rho = _correlation(correlations, i, j, count)
                if rho is None:
                    rho = 1.0 if i == j else 0.0
                variance += contributions[i] * contributions[j] * rho
    if variance <= 0:
        return None
    if correlations is None:
        return [value * value / variance for value in contributions]
    marginal = [sum(contributions[j] * _rho_or(correlations, i, j, count) for j in range(count)) for i in range(count)]
    return [(w[i] or 0.0) * marginal[i] / variance for i in range(count)]


def _rho_or(correlations: Sequence[Sequence[float]], i: int, j: int, count: int) -> float:
    value = _correlation(correlations, i, j, count)
    if value is not None:
        return value
    return 1.0 if i == j else 0.0


# ── 参考区间对比 ─────────────────────────────────────────────────


def reference_bands(risk_preference: Any) -> tuple[str, dict[str, tuple[float, float]] | None]:
    """按用户风险偏好返回 (口径标签, 三档参考区间)。

    风险偏好可识别时返回 ``("R1".."R5", bands)``；无法识别（未提供或取值非法）时
    返回 ``("generic", None)``——不猜用户偏好，也不给未支持的区间对比。
    """
    from finance_agent.product_research.rules import normalize_profile_risk

    level = normalize_profile_risk(risk_preference)
    if level is None or level not in REFERENCE_BANDS:
        return _GENERIC_BASIS, None
    return level, REFERENCE_BANDS[level]


def band_deviation(
    weights_by_tier: Mapping[str, float],
    bands: Mapping[str, tuple[float, float]] | None,
) -> list[dict[str, Any]]:
    """当前三档占比与参考区间的偏离。

    ``bands`` 为空（未提供画像）时返回空列表。每项状态为
    ``below`` / ``within`` / ``above``，并给出到最近边界的小数距离。
    """
    if not bands:
        return []
    result: list[dict[str, Any]] = []
    for tier in _TIER_KEYS:
        band = bands.get(tier)
        if band is None:
            continue
        low, high = band
        weight = float(weights_by_tier.get(tier, 0.0) or 0.0)
        if weight < low:
            status, distance = "below", low - weight
        elif weight > high:
            status, distance = "above", weight - high
        else:
            status, distance = "within", 0.0
        result.append({
            "tier": tier,
            "weight": round(weight, 6),
            "reference_low": low,
            "reference_high": high,
            "status": status,
            "distance": round(distance, 6),
        })
    return result


# ── 汇总入口 ─────────────────────────────────────────────────────


def _default_risk_free() -> float:
    from finance_agent import config

    return float(getattr(config, "ALLOCATION_RISK_FREE_RATE", 0.02))


def _default_weight_bounds() -> tuple[float, float]:
    from finance_agent import config

    return (
        float(getattr(config, "ALLOCATION_WEIGHT_MIN", 0.0)),
        float(getattr(config, "ALLOCATION_WEIGHT_MAX", 1.0)),
    )


def _priced_holdings(holdings: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    priced: list[Mapping[str, Any]] = []
    for item in holdings:
        value = _finite(item.get("market_value"))
        if value is not None and value > 0:
            priced.append(item)
    return priced

def review_portfolio(
    holdings: Sequence[Mapping[str, Any]],
    account: Mapping[str, Any] | None = None,
    profile: Mapping[str, Any] | None = None,
    *,
    risk_free: float | None = None,
    weight_min: float | None = None,
    weight_max: float | None = None,
) -> dict[str, Any]:
    """把一个用户的持仓汇总为配置诊断。

    ``holdings`` 每项至少含 ``product_code``/``market_value``，可选
    ``product_name``/``volatility``/``return_1y``/``max_drawdown``/``risk_level``。

    缺净值（``market_value`` 为空或非正）的持仓不参与占比计算，登记进
    ``limitations``——不静默缩小分母（与 ``PortfolioService`` 的口径一致）。
    未提供可识别风险偏好时不猜偏好、不给区间对比，只出集中度与风险暴露。
    """
    account = account or {}
    profile = profile or {}
    zero_correlation = True  # 无净值时序 → 只能对角近似
    rf = _default_risk_free() if risk_free is None else float(risk_free)
    if weight_min is None or weight_max is None:
        default_min, default_max = _default_weight_bounds()
        weight_min = default_min if weight_min is None else weight_min
        weight_max = default_max if weight_max is None else weight_max

    priced = _priced_holdings(holdings)
    unpriced = [
        item for item in holdings
        if not (_finite(item.get("market_value")) or 0.0) > 0
    ]
    limitations: list[str] = []

    if not priced:
        return {
            "profile_used": False,
            "risk_preference": None,
            "reference_basis": _GENERIC_BASIS,
            "position_count": 0,
            "holdings": [],
            "tiers": {tier: 0.0 for tier in _TIER_KEYS} | {TIER_UNKNOWN: 0.0},
            "concentration": concentration_metrics([]),
            "portfolio": {
                "expected_return": None, "volatility": None, "sharpe": None,
                "max_drawdown": None, "diversification_ratio": None,
            },
            "risk_contribution": [],
            "reference_weights": {},
            "deviations": [],
            "cash_ratio": _cash_ratio(account),
            "assumptions": {
                "risk_free_rate": rf,
                "zero_correlation": zero_correlation,
                "weight_min": weight_min,
                "weight_max": weight_max,
            },
            "notes": [],
            "limitations": ["no_priced_holdings"],
            "approximation": "zero_correlation",
            "unpriced": [_code_of(item) for item in holdings],
        }

    market_values = [_finite(item.get("market_value")) or 0.0 for item in priced]
    weights = normalize_weights(market_values)
    total_market_value = sum(market_values)

    # 三档占比（按产品风险等级归并）。
    tier_totals: dict[str, float] = {tier: 0.0 for tier in _TIER_KEYS}
    tier_totals[TIER_UNKNOWN] = 0.0
    for item, weight in zip(priced, weights):
        tier = _tier_of(item.get("risk_level"))
        tier_totals[tier] += weight

    # 风险指标只覆盖同时具备对应标量的持仓。
    stat_items = [
        (item, weight)
        for item, weight in zip(priced, weights)
        if _finite(item.get("volatility")) is not None
    ]
    if len(stat_items) < len(priced):
        limitations.append("partial_risk_metrics")
    stat_weights = normalize_weights([weight for _, weight in stat_items]) if stat_items else []
    stat_vols = [_finite(item.get("volatility")) for item, _ in stat_items]
    stat_returns = [_finite(item.get("return_1y")) for item, _ in stat_items]
    stat_drawdowns = [_finite(item.get("max_drawdown")) for item, _ in stat_items]

    volatility = portfolio_volatility(stat_weights, stat_vols) if stat_items else None
    expected_return = portfolio_return(stat_weights, stat_returns) if stat_items else None
    max_drawdown = portfolio_max_drawdown(stat_weights, stat_drawdowns) if stat_items else None
    sharpe = portfolio_sharpe(expected_return, volatility, rf) if stat_items else None
    div_ratio = (
        diversification_ratio(stat_weights, stat_vols) if stat_items else None
    )

    # 测算参考权重（数学口径，不是建议）：等权 / 逆波动率 / 风险平价。
    reference_weights: dict[str, Any] = {}
    if stat_items:
        codes = [_code_of(item) for item, _ in stat_items]
        reference_weights = {
            "labels": codes,
            "equal_weight": _round_list(
                constrained_weights(equal_weight(len(stat_items)), weight_min, weight_max)
            ),
            "inverse_volatility": _round_list(
                constrained_weights(inverse_volatility_weights(stat_vols), weight_min, weight_max)
            ),
            "risk_parity": _round_list(
                constrained_weights(risk_budget_weights(stat_vols), weight_min, weight_max)
            ),
        }

    basis, bands = reference_bands(profile.get("risk_preference"))
    profile_used = bands is not None
    deviations = band_deviation(tier_totals, bands)
    if not profile_used:
        limitations.append("profile_missing")

    notes: list[str] = [
        "参考区间为固定演示模型，仅用于展示当前配置与风险偏好的偏离，不构成投资建议。",
        "测算参考权重为数学口径（等权/逆波动率/风险平价），未考虑相关性，不是调仓建议。",
    ]

    contributions = risk_contribution(stat_weights, stat_vols) if stat_items else None
    contribution_rows: list[dict[str, Any]] = []
    if contributions and stat_items:
        for (item, _), contribution in zip(stat_items, contributions):
            contribution_rows.append({
                "product_code": _code_of(item),
                "product_name": str(item.get("product_name") or ""),
                "contribution": round(contribution, 6),
            })

    return {
        "profile_used": profile_used,
        "risk_preference": basis if profile_used else None,
        "reference_basis": basis,
        "position_count": len(priced),
        "total_market_value": round(total_market_value, 2),
        "holdings": [
            {
                "product_code": _code_of(item),
                "product_name": str(item.get("product_name") or ""),
                "weight": round(weight, 6),
                "risk_level": str(item.get("risk_level") or ""),
                "tier": _tier_of(item.get("risk_level")),
                "volatility": _finite(item.get("volatility")),
                "return_1y": _finite(item.get("return_1y")),
            }
            for item, weight in zip(priced, weights)
        ],
        "tiers": {tier: round(value, 6) for tier, value in tier_totals.items()},
        "concentration": concentration_metrics(weights),
        "portfolio": {
            "expected_return": _round_or_none(expected_return),
            "volatility": _round_or_none(volatility),
            "sharpe": _round_or_none(sharpe),
            "max_drawdown": _round_or_none(max_drawdown),
            "diversification_ratio": _round_or_none(div_ratio),
        },
        "risk_contribution": contribution_rows,
        "reference_weights": reference_weights,
        "deviations": deviations,
        "cash_ratio": _cash_ratio(account),
        "assumptions": {
            "risk_free_rate": rf,
            "zero_correlation": zero_correlation,
            "weight_min": float(weight_min),
            "weight_max": float(weight_max),
        },
        "notes": notes,
        "limitations": limitations,
        "approximation": "zero_correlation",
        "unpriced": [_code_of(item) for item in unpriced],
    }


def _code_of(item: Mapping[str, Any]) -> str:
    return str(item.get("product_code") or item.get("code") or "")


def _tier_of(risk_level: Any) -> str:
    from finance_agent.product_research.rules import normalize_risk

    level = normalize_risk(risk_level)
    return _TIER_BY_RISK.get(level or "", TIER_UNKNOWN)


def _round_or_none(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


def _round_list(values: Sequence[float]) -> list[float]:
    return [round(value, 6) for value in values]


def _cash_ratio(account: Mapping[str, Any]) -> float | None:
    cash = _finite(account.get("cash_balance"))
    total = _finite(account.get("total_assets"))
    if cash is None or total is None or total <= 0:
        return None
    return round(cash / total, 6)


__all__ = [
    "REFERENCE_BANDS",
    "TIER_HIGH",
    "TIER_LOW",
    "TIER_MID",
    "TIER_UNKNOWN",
    "band_deviation",
    "concentration_metrics",
    "constrained_weights",
    "diversification_ratio",
    "equal_weight",
    "inverse_volatility_weights",
    "normalize_weights",
    "portfolio_max_drawdown",
    "portfolio_return",
    "portfolio_sharpe",
    "portfolio_volatility",
    "reference_bands",
    "review_portfolio",
    "risk_budget_weights",
    "risk_contribution",
]
