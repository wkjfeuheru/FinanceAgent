"""技术指标计算模块。

基于K线数据（open/close/high/low/volume）计算常用技术指标。
纯 Python 实现，零外部依赖。每个函数接收 list[float]，返回 dict。
"""

from __future__ import annotations

from typing import Any

# 指标名称映射（tool 参数可能用的大小写变体）
INDICATOR_NAMES: dict[str, str] = {
    "macd": "MACD",
    "kdj": "KDJ",
    "rsi": "RSI",
    "boll": "BOLL",
    "ma": "MA",
    "wr": "WR",
    "m.a.": "MA",
    "布林": "BOLL",
    "威廉": "WR",
}


def _ema(data: list[float], period: int) -> list[float]:
    """计算指数移动平均（EMA），返回与输入等长的序列。"""
    if len(data) < period:
        return [sum(data) / len(data)] * len(data)
    k = 2.0 / (period + 1.0)
    result = [sum(data[:period]) / period]
    for price in data[period:]:
        result.append(price * k + result[-1] * (1.0 - k))
    return [result[0]] * (period - 1) + result


def _sma(data: list[float], period: int) -> list[float]:
    """简单移动平均（SMA）。"""
    if len(data) < period:
        return [sum(data) / len(data)] * len(data)
    result = []
    window_sum = sum(data[:period])
    result.append(window_sum / period)
    for i in range(period, len(data)):
        window_sum += data[i] - data[i - period]
        result.append(window_sum / period)
    return [result[0]] * (period - 1) + result


def _stddev(data: list[float], period: int) -> list[float]:
    """滚动标准差。"""
    sma_vals = _sma(data, period)
    result = []
    for i in range(len(data)):
        start = max(0, i - period + 1)
        window = data[start:i + 1]
        mean = sum(window) / len(window)
        variance = sum((x - mean) ** 2 for x in window) / len(window)
        result.append(variance ** 0.5)
    return result


def _recent(values: list[float], count: int = 5) -> list[float]:
    """取序列最后 count 个值。"""
    return values[-count:] if len(values) >= count else list(values)


def _cross_up(a: list[float], b: list[float]) -> int | None:
    """最近一次上穿（金叉）发生的距今位置。None 表示未发生。"""
    for i in range(len(a) - 2, max(len(a) - 60, 0), -1):
        if a[i] <= b[i] and a[i + 1] > b[i + 1]:
            return len(a) - 1 - (i + 1)
    return None


def _cross_down(a: list[float], b: list[float]) -> int | None:
    """最近一次下穿（死叉）发生的距今位置。"""
    for i in range(len(a) - 2, max(len(a) - 60, 0), -1):
        if a[i] >= b[i] and a[i + 1] < b[i + 1]:
            return len(a) - 1 - (i + 1)
    return None


# ── 公开指标函数 ──────────────────────────────────────────────────

def calc_ma(close: list[float], periods: list[int] | None = None) -> dict[str, Any]:
    """移动均线。

    Args:
        close: 收盘价序列（按时间升序）
        periods: 均线周期列表，默认 [5, 10, 20, 60]

    Returns:
        {"name": "MA", "values": {"MA5": [...], "MA10": [...]},
         "latest": {"MA5": 12.34, ...},
         "position": "价格位于5日线上方，10日线下方...",
         "trend": {"MA5": "上升", "MA10": "走平", ...}}
    """
    if periods is None:
        periods = [5, 10, 20, 60]
    result: dict[str, Any] = {"name": "MA", "values": {}, "latest": {}, "trend": {}}
    latest_price = close[-1] if close else 0
    for p in periods:
        ma_vals = _sma(close, p)
        result["values"][f"MA{p}"] = _recent(ma_vals, 5)
        result["latest"][f"MA{p}"] = round(ma_vals[-1], 4) if ma_vals else 0
        if len(ma_vals) >= 3:
            delta = ma_vals[-1] - ma_vals[-3]
            if delta > 0.001:
                result["trend"][f"MA{p}"] = "上升"
            elif delta < -0.001:
                result["trend"][f"MA{p}"] = "下降"
            else:
                result["trend"][f"MA{p}"] = "走平"
    # 价格与均线位置关系
    above = [f"MA{p}" for p in periods if result["latest"].get(f"MA{p}", 0) < latest_price]
    below = [f"MA{p}" for p in periods if result["latest"].get(f"MA{p}", 0) > latest_price]
    parts = []
    if above:
        parts.append(f"价格位于{'、'.join(above)}上方")
    if below:
        parts.append(f"价格位于{'、'.join(below)}下方")
    result["position"] = "；".join(parts) if parts else "价格与均线交织"
    return result


def calc_macd(
    close: list[float], fast: int = 12, slow: int = 26, signal: int = 9,
) -> dict[str, Any]:
    """MACD 指标。

    Returns:
        {"name": "MACD", "params": {...}, "latest": {"DIF": ..., "DEA": ..., "histogram": ...},
         "signal": "金叉" | "死叉" | None,
         "divergence": "顶背离" | "底背离" | None,
         "trend": "多头" | "空头" | "震荡",
         "values": {"2024-07-22": {"DIF": ..., "DEA": ..., "histogram": ...}, ...}}
    """
    dif_vals = [e_f - e_s for e_f, e_s in zip(_ema(close, fast), _ema(close, slow))]
    dea_vals = _ema(dif_vals, signal)
    hist_vals = [2.0 * (d - e) for d, e in zip(dif_vals, dea_vals)]

    cross_up_pos = _cross_up(dif_vals, dea_vals)
    cross_down_pos = _cross_down(dif_vals, dea_vals)
    if cross_up_pos is not None and (
        cross_down_pos is None or cross_up_pos < cross_down_pos
    ):
        sig = "金叉"
    elif cross_down_pos is not None and (
        cross_up_pos is None or cross_down_pos < cross_up_pos
    ):
        sig = "死叉"
    else:
        sig = None

    # 趋势判断
    if dif_vals[-1] > dea_vals[-1] and dif_vals[-1] > 0:
        trend = "多头"
    elif dif_vals[-1] < dea_vals[-1] and dif_vals[-1] < 0:
        trend = "空头"
    else:
        trend = "震荡"

    # 简化背离判断（价格创 N 日新高/新低但 DIF 未跟随）
    divergence = None
    lookback = min(20, len(close) - 1)
    if lookback >= 10:
        price_high_idx = close.index(max(close[-lookback:]))
        dif_high_idx = dif_vals.index(max(dif_vals[-lookback:]))
        price_low_idx = close.index(min(close[-lookback:]))
        dif_low_idx = dif_vals.index(min(dif_vals[-lookback:]))
        if price_high_idx > dif_high_idx + 3:
            divergence = "顶背离"
        elif price_low_idx > dif_low_idx + 3:
            divergence = "底背离"

    recent = min(5, len(close))
    values_map = {}
    for i in range(len(close) - recent, len(close)):
        if i >= 0:
            values_map[str(i)] = {
                "DIF": round(dif_vals[i], 4),
                "DEA": round(dea_vals[i], 4),
                "histogram": round(hist_vals[i], 4),
            }

    return {
        "name": "MACD",
        "params": {"fast": fast, "slow": slow, "signal": signal},
        "latest": {
            "DIF": round(dif_vals[-1], 4),
            "DEA": round(dea_vals[-1], 4),
            "histogram": round(hist_vals[-1], 4),
        },
        "signal": sig,
        "divergence": divergence,
        "trend": trend,
        "values": values_map,
    }


def calc_kdj(
    high: list[float], low: list[float], close: list[float],
    n: int = 9, m1: int = 3, m2: int = 3,
) -> dict[str, Any]:
    """KDJ 指标。

    Returns:
        {"name": "KDJ", "params": {...}, "latest": {"K": ..., "D": ..., "J": ...},
         "signal": "金叉" | "死叉" | None,
         "zone": "超买" | "超卖" | "正常",
         "values": {...}}
    """
    n_days = len(close)
    k_vals: list[float] = [50.0] * n_days
    d_vals: list[float] = [50.0] * n_days
    j_vals: list[float] = [50.0] * n_days

    prev_k = 50.0
    prev_d = 50.0
    for i in range(n_days):
        if i < n - 1:
            k_vals[i] = 50.0
            d_vals[i] = 50.0
            j_vals[i] = 50.0
            continue
        window_high = max(high[max(0, i - n + 1):i + 1])
        window_low = min(low[max(0, i - n + 1):i + 1])
        rsv = ((close[i] - window_low) / (window_high - window_low) * 100.0
               if window_high != window_low else 50.0)
        k = (2.0 / (m1 + 1)) * rsv + (1.0 - 2.0 / (m1 + 1)) * prev_k
        d = (2.0 / (m2 + 1)) * k + (1.0 - 2.0 / (m2 + 1)) * prev_d
        j = 3.0 * k - 2.0 * d
        k_vals[i] = k
        d_vals[i] = d
        j_vals[i] = j
        prev_k = k
        prev_d = d

    cross_up_pos = _cross_up(k_vals, d_vals)
    cross_down_pos = _cross_down(k_vals, d_vals)
    if cross_up_pos is not None and (
        cross_down_pos is None or cross_up_pos < cross_down_pos
    ):
        sig = "金叉"
    elif cross_down_pos is not None and (
        cross_up_pos is None or cross_down_pos < cross_up_pos
    ):
        sig = "死叉"
    else:
        sig = None

    latest_k = k_vals[-1]
    if latest_k > 80:
        zone = "超买"
    elif latest_k < 20:
        zone = "超卖"
    else:
        zone = "正常"

    recent = min(5, n_days)
    values_map = {}
    for i in range(n_days - recent, n_days):
        if i >= 0:
            values_map[str(i)] = {
                "K": round(k_vals[i], 2),
                "D": round(d_vals[i], 2),
                "J": round(j_vals[i], 2),
            }

    return {
        "name": "KDJ",
        "params": {"n": n, "m1": m1, "m2": m2},
        "latest": {"K": round(k_vals[-1], 2), "D": round(d_vals[-1], 2), "J": round(j_vals[-1], 2)},
        "signal": sig,
        "zone": zone,
        "values": values_map,
    }


def calc_rsi(
    close: list[float], periods: list[int] | None = None,
) -> dict[str, Any]:
    """RSI 指标。

    Returns:
        {"name": "RSI", "latest": {"RSI6": ..., "RSI12": ..., "RSI24": ...},
         "zones": {"RSI6": "超买"|"超卖"|"正常", ...},
         "values": {"RSI6": [最近5个], ...}}
    """
    if periods is None:
        periods = [6, 12, 24]
    result: dict[str, Any] = {"name": "RSI", "latest": {}, "zones": {}, "values": {}}

    for p in periods:
        gains = []
        losses = []
        for i in range(1, len(close)):
            diff = close[i] - close[i - 1]
            gains.append(diff if diff > 0 else 0.0)
            losses.append(-diff if diff < 0 else 0.0)
        avg_gain = sum(gains[:p]) / p if len(gains) >= p else (sum(gains) / max(1, len(gains)))
        avg_loss = sum(losses[:p]) / p if len(losses) >= p else (sum(losses) / max(1, len(losses)))
        rsi_vals = []
        for i in range(len(gains)):
            if i >= p:
                avg_gain = (avg_gain * (p - 1) + gains[i]) / p
                avg_loss = (avg_loss * (p - 1) + losses[i]) / p
            rs = avg_gain / avg_loss if avg_loss > 0 else 100.0
            rsi_vals.append(round(100.0 - 100.0 / (1.0 + rs), 2))
        key = f"RSI{p}"
        result["latest"][key] = rsi_vals[-1] if rsi_vals else 0
        result["values"][key] = _recent(rsi_vals, 5)
        latest = rsi_vals[-1] if rsi_vals else 50
        if latest > 80:
            result["zones"][key] = "超买"
        elif latest < 20:
            result["zones"][key] = "超卖"
        else:
            result["zones"][key] = "正常"
    return result


def calc_boll(
    close: list[float], period: int = 20, std_multiplier: float = 2.0,
) -> dict[str, Any]:
    """BOLL 布林带。

    Returns:
        {"name": "BOLL", "params": {...}, "latest": {"MID": ..., "UPPER": ..., "LOWER": ...},
         "bandwidth": ..., "position": "触及上轨"|"触及下轨"|"轨内",
         "values": {...}}
    """
    mid_vals = _sma(close, period)
    std_vals = _stddev(close, period)
    upper_vals = [m + std_multiplier * s for m, s in zip(mid_vals, std_vals)]
    lower_vals = [m - std_multiplier * s for m, s in zip(mid_vals, std_vals)]

    width = (upper_vals[-1] - lower_vals[-1]) / mid_vals[-1] * 100 if mid_vals[-1] > 0 else 0
    latest_price = close[-1] if close else 0

    if latest_price >= upper_vals[-1] * 0.99:
        position = "触及上轨"
    elif latest_price <= lower_vals[-1] * 1.01:
        position = "触及下轨"
    else:
        position = "轨内"

    recent = min(5, len(close))
    values_map = {}
    for i in range(len(close) - recent, len(close)):
        if i >= 0:
            values_map[str(i)] = {
                "MID": round(mid_vals[i], 4),
                "UPPER": round(upper_vals[i], 4),
                "LOWER": round(lower_vals[i], 4),
            }

    return {
        "name": "BOLL",
        "params": {"period": period, "std": std_multiplier},
        "latest": {
            "MID": round(mid_vals[-1], 4),
            "UPPER": round(upper_vals[-1], 4),
            "LOWER": round(lower_vals[-1], 4),
        },
        "bandwidth": round(width, 2),
        "position": position,
        "values": values_map,
    }


def calc_wr(
    high: list[float], low: list[float], close: list[float],
    periods: list[int] | None = None,
) -> dict[str, Any]:
    """WR 威廉指标。

    Returns:
        {"name": "WR", "latest": {"WR10": ..., "WR6": ...},
         "zones": {"WR10": "超买"|"超卖"|"正常", ...},
         "values": {...}}
    """
    if periods is None:
        periods = [10, 6]
    result: dict[str, Any] = {"name": "WR", "latest": {}, "zones": {}, "values": {}}

    for p in periods:
        wr_vals = []
        for i in range(len(close)):
            if i < p - 1:
                wr_vals.append(-50.0)
                continue
            window_high = max(high[i - p + 1:i + 1])
            window_low = min(low[i - p + 1:i + 1])
            wr = ((window_high - close[i]) / (window_high - window_low) * -100.0
                  if window_high != window_low else -50.0)
            wr_vals.append(round(wr, 2))
        key = f"WR{p}"
        result["latest"][key] = wr_vals[-1] if wr_vals else -50
        result["values"][key] = _recent(wr_vals, 5)
        latest = wr_vals[-1] if wr_vals else -50
        if latest > -20:
            result["zones"][key] = "超买"
        elif latest < -80:
            result["zones"][key] = "超卖"
        else:
            result["zones"][key] = "正常"
    return result


def compute_all_indicators(
    high: list[float],
    low: list[float],
    close: list[float],
    indicators: list[str] | None = None,
) -> dict[str, Any]:
    """批量计算技术指标。

    Args:
        high/low/close: K线价格序列
        indicators: 需要计算的指标名列表，如 ["MACD", "KDJ"]。
                    传 None 计算全部 6 个指标。

    Returns:
        {"MACD": {...}, "KDJ": {...}, ...}，仅包含请求的指标；
        同时也返回 summary 字段汇总关键信号。
    """
    if indicators is not None:
        requested = set(name.upper().strip() for name in indicators)
        normalized = set()
        for raw in requested:
            # 尝试匹配 INDICATOR_NAMES
            matched = False
            for alias, standard in INDICATOR_NAMES.items():
                if raw == alias.upper() or raw == standard.upper():
                    normalized.add(standard)
                    matched = True
                    break
            if not matched:
                normalized.add(raw)
    else:
        normalized = {"MACD", "KDJ", "RSI", "BOLL", "MA", "WR"}

    result: dict[str, Any] = {}
    signals: list[str] = []
    risks: list[str] = []

    if "MA" in normalized:
        result["MA"] = calc_ma(close)

    if "MACD" in normalized:
        macd = calc_macd(close)
        result["MACD"] = macd
        if macd.get("signal") == "金叉":
            signals.append("MACD金叉信号")
        elif macd.get("signal") == "死叉":
            risks.append("MACD死叉信号")
        if macd.get("divergence"):
            if "顶背离" in str(macd["divergence"]):
                risks.append("MACD顶背离")
            elif "底背离" in str(macd["divergence"]):
                signals.append("MACD底背离")

    if "KDJ" in normalized:
        kdj = calc_kdj(high, low, close)
        result["KDJ"] = kdj
        if kdj.get("signal") == "金叉":
            signals.append("KDJ金叉信号")
        elif kdj.get("signal") == "死叉":
            risks.append("KDJ死叉信号")
        if kdj.get("zone"):
            sig = f"KDJ{kdj['zone']}"
            (signals if kdj["zone"] == "超卖" else risks).append(sig)

    if "RSI" in normalized:
        rsi = calc_rsi(close)
        result["RSI"] = rsi
        for key, zone in rsi.get("zones", {}).items():
            if zone == "超卖":
                signals.append(f"{key}超卖")
            elif zone == "超买":
                risks.append(f"{key}超买")

    if "BOLL" in normalized:
        boll = calc_boll(close)
        result["BOLL"] = boll
        pos = boll.get("position", "")
        if pos == "触及下轨":
            signals.append("BOLL触及下轨（潜在支撑）")
        elif pos == "触及上轨":
            risks.append("BOLL触及上轨（潜在压力）")

    if "WR" in normalized:
        wr = calc_wr(high, low, close)
        result["WR"] = wr
        for key, zone in wr.get("zones", {}).items():
            if zone == "超卖":
                signals.append(f"{key}超卖")
            elif zone == "超买":
                risks.append(f"{key}超买")

    latest_price = close[-1] if close else 0
    # 趋势综合判断（基于 MA + MACD）
    trend = "震荡"
    if "MA" in result and "MACD" in result:
        ma5 = result["MA"]["latest"].get("MA5", 0)
        ma20 = result["MA"]["latest"].get("MA20", 0)
        macd_trend = result["MACD"].get("trend", "震荡")
        if latest_price > ma5 > ma20 and macd_trend == "多头":
            trend = "上升"
        elif latest_price < ma5 < ma20 and macd_trend == "空头":
            trend = "下降"

    result["summary"] = {
        "trend": trend,
        "signals": signals,
        "risks": risks,
        "latest_price": round(latest_price, 4),
    }
    return result
