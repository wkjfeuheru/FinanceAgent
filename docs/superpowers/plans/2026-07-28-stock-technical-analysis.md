# Stock Analysis Agent — 技术面扩展 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `FundamentalAnalysisAgent` 重构为 `StockAnalysisAgent`，通过 ReAct Agent 自主决策执行基本面分析、技术面分析或两者，技术指标（MACD/KDJ/RSI/BOLL/MA/WR）基于K线数据纯 Python 自算。

**Architecture:** 在 Agent 内部使用 `create_react_agent` + `bind_tools([analyze_fundamentals, analyze_technicals])`。Agent 接收近期对话摘要 + 当前用户问题 + 可用数据描述，ReAct 推理选择调用哪个工具。工具返回结构化 JSON，Agent 合成最终回复。指标计算为独立纯 Python 模块，零外部依赖。

**Tech Stack:** Python 3.10+, LangChain/LangGraph (已有), DeepSeek v4-pro (已有)

## Global Constraints

- 技术指标零外部依赖（不安装 ta-lib / pandas-ta）
- Supervisor 层不新增意图，不修改 GLM 分类器
- `data_fetch.py` 不做修改（K线已通过 `get_stock_history` 获取）
- `handle()` 方法签名保持不变，向后兼容
- 用户指定具体指标时只输出指定指标，不堆砌全部指标
- 现有 checkpoint 数据格式兼容

---

### Task 1: 创建技术指标计算模块

**Files:**
- Create: `finance_agent/tools/technical_indicators.py`

**Interfaces:**
- Produces: `calc_ma(close, periods) -> dict`, `calc_macd(close, fast, slow, signal) -> dict`, `calc_kdj(high, low, close, n, m1, m2) -> dict`, `calc_rsi(close, periods) -> dict`, `calc_boll(close, period, std) -> dict`, `calc_wr(high, low, close, periods) -> dict`, `compute_all_indicators(high, low, close, indicators=None) -> dict`, `INDICATOR_NAMES: dict[str, str]`
- Consumes: nothing — pure functions, no I/O

- [ ] **Step 1: 创建空模块文件**

Run: `if (-not (Test-Path "f:/python project/FinanceAgent/finance_agent/tools/technical_indicators.py")) { New-Item -ItemType File -Path "f:/python project/FinanceAgent/finance_agent/tools/technical_indicators.py" }`

- [ ] **Step 2: 编写完整模块代码**（写入文件）

```python
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
```

- [ ] **Step 3: 验证模块可导入**

Run: `python -c "from finance_agent.tools.technical_indicators import calc_macd, calc_kdj, calc_rsi, calc_boll, calc_ma, calc_wr, compute_all_indicators; print('All imports OK')"`

Expected: `All imports OK`

- [ ] **Step 4: 手动验证计算逻辑**

Run:
```powershell
python -c "
import json
from finance_agent.tools.technical_indicators import compute_all_indicators
# 模拟 30 天 K 线数据
import random
random.seed(42)
close = [10.0 + i * 0.1 + random.uniform(-0.5, 0.5) for i in range(60)]
high  = [c + abs(random.uniform(0.1, 0.4)) for c in close]
low   = [c - abs(random.uniform(0.1, 0.4)) for c in close]
result = compute_all_indicators(high, low, close)
print(json.dumps({k: type(v).__name__ for k, v in result.items()}, ensure_ascii=False))
print('summary:', json.dumps(result.get('summary', {}), ensure_ascii=False))
"
```

Expected: 输出 7 个 key（MACD/KDJ/RSI/BOLL/MA/WR/summary）且 summary 含 trend/signals/risks

- [ ] **Step 5: 验证指定指标过滤**

Run:
```powershell
python -c "
import json
from finance_agent.tools.technical_indicators import compute_all_indicators
close = [10.0 + i * 0.1 for i in range(60)]
high  = [c + 0.3 for c in close]
low   = [c - 0.3 for c in close]
result = compute_all_indicators(high, low, close, indicators=['MACD', 'KDJ'])
print('Keys:', list(result.keys()))
assert 'MACD' in result and 'KDJ' in result
assert 'RSI' not in result and 'BOLL' not in result
print('PASS: only requested indicators returned')
"
```

Expected: `PASS: only requested indicators returned`

- [ ] **Step 6: 提交**

```bash
git add finance_agent/tools/technical_indicators.py
git commit -m "feat: add technical indicator calculation module (MACD/KDJ/RSI/BOLL/MA/WR)

Pure Python implementation based on K-line OHLC data.
Zero external dependencies. Each indicator returns structured
dict with latest values, signals, and rule-based judgments.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: 更新 tools/__init__.py 导出

**Files:**
- Modify: `finance_agent/tools/__init__.py`

**Interfaces:**
- Produces: exports `compute_all_indicators`, `INDICATOR_NAMES`
- Consumes: `finance_agent.tools.technical_indicators` module (Task 1)

- [ ] **Step 1: 添加导出**

在文件末尾（`"extract_investment_goal",\n]` 之后）添加：

```python
from finance_agent.tools.technical_indicators import (
    INDICATOR_NAMES,
    calc_boll,
    calc_kdj,
    calc_ma,
    calc_macd,
    calc_rsi,
    calc_wr,
    compute_all_indicators,
)
```

然后在 `__all__` 列表的结尾 `]` 之前添加：
```python
    "compute_all_indicators",
    "INDICATOR_NAMES",
    "calc_macd",
    "calc_kdj",
    "calc_rsi",
    "calc_boll",
    "calc_ma",
    "calc_wr",
```

精确的位置：

Read `finance_agent/tools/__init__.py` 的行 36-37:
```python
    "extract_investment_goal",
]
```

替换为:
```python
    "extract_investment_goal",
    "compute_all_indicators",
    "INDICATOR_NAMES",
    "calc_macd",
    "calc_kdj",
    "calc_rsi",
    "calc_boll",
    "calc_ma",
    "calc_wr",
]
```

并在文件顶部的 import block 末尾（`from finance_agent.tools.finance_slots import (` 块之后）添加新的 import 块：

```python
from finance_agent.tools.technical_indicators import (
    INDICATOR_NAMES,
    calc_boll,
    calc_kdj,
    calc_ma,
    calc_macd,
    calc_rsi,
    calc_wr,
    compute_all_indicators,
)
```

- [ ] **Step 2: 验证导入**

Run: `python -c "from finance_agent.tools import compute_all_indicators, INDICATOR_NAMES; print('Import OK')"`

Expected: `Import OK`

- [ ] **Step 3: 提交**

```bash
git add finance_agent/tools/__init__.py
git commit -m "feat: export technical indicator functions from tools package

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: 重构 stock_analysis.py — StockAnalysisAgent

**Files:**
- Modify: `finance_agent/agents/stock_analysis.py`（全量重写）

**Interfaces:**
- Consumes: `BaseFinanceAgent` (base.py), `get_model_for_agent` (config.py), `safe_parse_json` (config.py), `SharedWorkingMemory` (shared_state.py), `compute_all_indicators` (technical_indicators.py)
- Produces: `StockAnalysisAgent` class with `agent_name = "stock_analysis"`, `handle_single_stock(code, user_message="", memory_context="", chat_history=None) -> dict`, `handle(message, customer_id, chat_history, thread_id, memory_context) -> str`

- [ ] **Step 1: 读取当前文件确认内容**

`Read finance_agent/agents/stock_analysis.py`（已在上下文中）

- [ ] **Step 2: 写完整的重构文件**

用以下内容**全量替换** `finance_agent/agents/stock_analysis.py`：

```python
"""股票综合分析 Agent。

职责：根据用户输入自主决策，执行基本面分析、技术面分析或两者兼有。
- 基本面：盈利能力（ROE、净利率、毛利率）、成长性、估值（PE、PB）、财务健康
- 技术面：MACD、KDJ、RSI、BOLL、MA（均线）、WR（威廉指标）

通过 ReAct Agent 接收近期对话摘要 + 当前问题，自主 tool calling 选择
分析工具。当无法判断意图时主动追问。分析结果写入共享内存。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from langchain_core.messages import ToolMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool

from finance_agent.agents.base import BaseFinanceAgent
from finance_agent.config import get_model_for_agent, safe_parse_json
from finance_agent.tools.technical_indicators import compute_all_indicators


def _safe_score(value: Any, default: float = 50.0) -> float:
    """Convert an LLM score to float while tolerating null/empty/invalid values."""
    try:
        score = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(100.0, score))


_FUNDAMENTAL_ANALYSIS_PROMPT = """你是金融基本面分析专家。

## 身份
你负责分析A股上市公司的基本面情况，为投资决策提供依据。

## 分析维度

### 1. 盈利能力
- ROE（净资产收益率）：>15% 优秀，10-15% 良好，<10% 一般
- 净利率：反映盈利转化效率
- 毛利率：反映产品竞争力

### 2. 成长性
- 营收增长率：>20% 高成长，10-20% 稳健，<10% 低成长
- 净利润增长率：判断成长持续性

### 3. 估值水平
- PE（市盈率）：与行业均值对比
- PB（市净率）：判断是否高估/低估

### 4. 财务健康
- 资产负债率：<50% 健康，50-70% 中性，>70% 风险较高
- 流动比率/速动比率：>2 流动性好

## 输出格式
返回JSON：
{{
  "code": "股票代码",
  "name": "股票名称",
  "profitability": {{"score": 0-100, "analysis": "..."}},
  "growth": {{"score": 0-100, "analysis": "..."}},
  "valuation": {{"score": 0-100, "analysis": "..."}},
  "financial_health": {{"score": 0-100, "analysis": "..."}},
  "overall_score": 0-100,
  "rating": "推荐/中性/谨慎",
  "advantages": ["优势1", "优势2"],
  "risks": ["风险1", "风险2"],
  "summary": "一句话总结"
}}

## 规则
- 基于提供的财务指标数据进行分析，不要编造数据
- 如果数据缺失，明确指出
- 评级标准：overall_score >= 75 推荐，60-75 中性，<60 谨慎
- 语言要求：使用正式、专业的书面中文。不得使用口语化或网络用语表述。
  优势/风险描述应使用"盈利能力突出""估值处于合理区间""财务结构稳健"
  "流动性需关注"等专业措辞。summary 必须是一句完整的、有信息量的
  专业判断，不得使用空泛口语。"""


_STOCK_ANALYSIS_SYSTEM_PROMPT = """你是股票综合分析专家，拥有基本面分析和技术面分析两种专业能力。

## 可用工具
- `analyze_fundamentals`: 基于财务指标（ROE/PE/PB/利润增速/负债率等）分析基本面。
  适用场景：估值判断、盈利能力评估、财务健康检查、成长性分析。

- `analyze_technicals`: 基于K线数据计算技术指标（MACD/KDJ/RSI/BOLL/MA/WR）并解读走势。
  适用场景：买卖信号、趋势判断、超买超卖、支撑压力位。
  可通过 indicators 参数指定需要的指标，
  如 `analyze_technicals(stock_code="600519", indicators=["MACD","KDJ"])`。

## 决策规则
1. 用户明确提到"基本面/估值/财务/盈利/ROE/PE/PB/负债率"等关键词
   → 只调用 `analyze_fundamentals`
2. 用户明确提到"技术面/走势/形态/K线/趋势/买卖信号/超买/超卖"或
   具体指标名（MACD/KDJ/RSI/布林/BOLL/均线/MA/WR/威廉）
   → 只调用 `analyze_technicals`。
   若用户指定了具体指标，通过 indicators 参数传入
3. 用户说"全面分析/综合分析/整体评估"或同时提及两方面关键词
   → 调用两个工具
4. 若用户指定的指标在技术面工具不覆盖范围内，只计算能支持的指标并如实说明
5. 无法从对话判断意图 → 不要调用任何工具，追问
   "请问您需要基本面分析（估值、盈利能力等）还是技术面分析（MACD、KDJ等指标走势）？"

## 输出规则
- 只输出用户关心的分析维度，严格对应用户提问范围
- 用户只问技术面 → 回复只含技术面，不要夹杂基本面内容；反之同理
- 用户指定了具体指标 → 只输出这些指标的结果和解读，不要把全部指标堆砌上去
- 数据缺失时明确指出限制，不编造数据
- 使用正式、专业的书面中文"""


class StockAnalysisAgent(BaseFinanceAgent):
    """股票综合分析 Agent —— 基本面 + 技术面，ReAct 自主决策。"""

    agent_name: str = "stock_analysis"

    def __init__(self, shared_memory=None, checkpointer=None):
        super().__init__(shared_memory=shared_memory, checkpointer=checkpointer)
        # 基本面分析链（保持独立，供 tool 内部复用）
        self._fundamental_chain = None

    # ── 工具定义（闭包捕获 self，在 _get_tools() 中构造）──

    def _get_tools(self) -> list:
        agent_self = self

        @tool
        def analyze_fundamentals(stock_code: str) -> str:
            """对指定A股进行基本面分析。

            基于财务指标数据（ROE/PE/PB/净利率/营收增长率/负债率/流动比率等），
            从盈利能力、成长性、估值水平、财务健康四个维度评估。
            适用场景：用户关注估值、盈利能力、财务健康、成长性。

            Args:
                stock_code: 6位A股代码，如 600519

            Returns:
                JSON 格式的结构化分析结果
            """
            if not agent_self.shared_memory:
                return json.dumps({
                    "code": stock_code, "rating": "未知", "overall_score": 50,
                    "summary": "无共享内存，无法分析",
                }, ensure_ascii=False)

            indicators = agent_self.shared_memory.query(
                f"financial_indicator_{stock_code}", {},
            )
            basic_info = agent_self.shared_memory.query(
                f"stock_basic_info_{stock_code}", {},
            )

            if not indicators and not basic_info:
                return json.dumps({
                    "code": stock_code, "rating": "未知", "overall_score": 50,
                    "summary": "无财务数据，无法分析",
                }, ensure_ascii=False)

            financial_data = {
                "code": stock_code,
                "basic_info": basic_info or {},
                "indicators": indicators or {},
            }

            return agent_self._run_fundamental_chain(stock_code, financial_data)

        @tool
        def analyze_technicals(
            stock_code: str,
            indicators: list[str] | None = None,
        ) -> str:
            """对指定A股进行技术面分析。

            基于历史K线数据（最近一年日K线）计算指定技术指标并解读走势。
            可计算 MACD/KDJ/RSI/BOLL/MA/WR 六种指标。
            适用场景：用户关注走势、买卖信号、超买超卖、支撑压力位、趋势判断。

            Args:
                stock_code: 6位A股代码，如 600519
                indicators: 需要的指标列表，如 ["MACD","KDJ"]。
                            None 或空列表表示计算全部 6 个默认指标。

            Returns:
                JSON 格式的结构化技术面分析结果
            """
            if not agent_self.shared_memory:
                return json.dumps({
                    "error": "无共享内存，无法进行技术面分析",
                    "code": stock_code,
                }, ensure_ascii=False)

            history = agent_self.shared_memory.query(
                f"stock_history_{stock_code}", {},
            )
            if not history or "error" in history:
                return json.dumps({
                    "error": "无K线历史数据，无法进行技术面分析",
                    "code": stock_code,
                }, ensure_ascii=False)

            data_points = history.get("data")
            if not isinstance(data_points, list) or len(data_points) < 30:
                return json.dumps({
                    "error": f"K线数据不足（仅 {len(data_points) if isinstance(data_points, list) else 0} 条），最少需要 30 条",
                    "code": stock_code,
                }, ensure_ascii=False)

            try:
                high = [float(d["high"]) for d in data_points]
                low = [float(d["low"]) for d in data_points]
                close = [float(d["close"]) for d in data_points]
            except (KeyError, ValueError, TypeError) as exc:
                return json.dumps({
                    "error": f"K线数据格式异常：{exc}",
                    "code": stock_code,
                }, ensure_ascii=False)

            try:
                result = compute_all_indicators(high, low, close, indicators)
            except Exception as exc:
                return json.dumps({
                    "error": f"技术指标计算失败：{exc}",
                    "code": stock_code,
                }, ensure_ascii=False)

            return json.dumps(result, ensure_ascii=False)

        return [analyze_fundamentals, analyze_technicals]

    def _get_system_prompt(self) -> str:
        return _STOCK_ANALYSIS_SYSTEM_PROMPT

    # ── 基本面分析 LLM 链（tool 内部复用）──

    @property
    def fundamental_chain(self):
        """独立的基本面分析 LLM 链。"""
        if self._fundamental_chain is None:
            prompt = ChatPromptTemplate.from_messages([
                ("system", _FUNDAMENTAL_ANALYSIS_PROMPT),
                ("human", "股票财务数据：\n{financial_data}\n\n请进行基本面分析："),
            ])
            self._fundamental_chain = (
                prompt
                | get_model_for_agent("fundamental")
                | StrOutputParser()
            )
        return self._fundamental_chain

    def _run_fundamental_chain(
        self, stock_code: str, financial_data: Dict[str, Any],
    ) -> str:
        """执行基本面分析 LLM 链并返回 JSON 字符串。"""
        try:
            result = self.fundamental_chain.invoke({
                "financial_data": json.dumps(
                    financial_data, ensure_ascii=False, default=str,
                ) if isinstance(financial_data, dict) else str(financial_data),
            })
            parsed = safe_parse_json(result, {
                "code": stock_code,
                "overall_score": 50,
                "rating": "中性",
                "summary": "基本面分析解析失败",
            })
        except Exception:
            parsed = {
                "code": stock_code,
                "overall_score": 50,
                "rating": "中性",
                "summary": "基本面分析执行异常",
            }

        parsed["code"] = stock_code
        parsed["overall_score"] = _safe_score(parsed.get("overall_score"))
        return json.dumps(parsed, ensure_ascii=False)

    # ── 上下文构建 ──

    def _build_analysis_context(
        self,
        code: str,
        indicators: Dict[str, Any],
        basic_info: Dict[str, Any],
        history: Dict[str, Any],
        user_message: str,
        memory_context: str,
    ) -> str:
        """构建 ReAct Agent 的输入上下文。"""

        parts = []

        # 用户当前问题
        if user_message:
            parts.append(f"## 当前用户问题\n{user_message}")
        else:
            name = (basic_info.get("name") or code) if isinstance(basic_info, dict) else code
            parts.append(f"## 当前用户问题\n请分析股票 {code}「{name}」")

        # 对话上下文
        if memory_context:
            # 截断过长的上下文
            ctx = memory_context[:3000] if len(memory_context) > 3000 else memory_context
            parts.append(f"## 近期对话摘要\n{ctx}")

        # 可用数据描述
        available = []
        has_financial = (
            isinstance(indicators, dict)
            and indicators
            and "error" not in indicators
        )
        has_history = (
            isinstance(history, dict)
            and history.get("data")
            and "error" not in history
        )
        history_count = (
            len(history.get("data", []))
            if isinstance(history, dict) and isinstance(history.get("data"), list)
            else 0
        )

        if has_financial:
            available.append("财务指标数据 已就绪（ROE/PE/PB/营收增速/负债率等）")
        else:
            available.append("财务指标数据 缺失或不可用")
        if has_history:
            available.append(f"K线历史数据 已就绪（最近 {history_count} 个交易日）")
        else:
            available.append("K线历史数据 缺失或不可用")

        parts.append(f"## 可用数据\n" + "\n".join(f"- {item}" for item in available))

        parts.append(
            f"\n请根据用户问题和对话上下文，判断需要执行哪种分析，"
            f"然后调用对应工具。如无法判断意图请直接追问。"
        )

        return "\n\n".join(parts)

    # ── 核心方法 ──

    def handle_single_stock(
        self,
        code: str,
        user_message: str = "",
        memory_context: str = "",
        chat_history: list[dict] | None = None,
    ) -> Dict[str, Any]:
        """分析单只股票并写入共享内存。

        通过 ReAct Agent 自主决策执行基本面分析、技术面分析或两者。
        结果发布回共享内存。

        Args:
            code: 6位A股代码
            user_message: 当前轮用户原始输入（可空，回退为默认提示）
            memory_context: 近期对话摘要等记忆上下文
            chat_history: 原始对话历史（预留）

        Returns:
            结构化分析结果 dict（含可选 technical_analysis 字段）
        """
        if not self.shared_memory:
            return {"code": code, "rating": "未知", "summary": "无共享内存"}

        indicators = self.shared_memory.query(f"financial_indicator_{code}", {})
        basic_info = self.shared_memory.query(f"stock_basic_info_{code}", {})
        history = self.shared_memory.query(f"stock_history_{code}", {})

        # 构建上下文
        context = self._build_analysis_context(
            code, indicators, basic_info, history,
            user_message, memory_context,
        )

        # ReAct Agent 执行
        try:
            result = self.agent.invoke(
                {"messages": [{"role": "user", "content": context}]},
                config={
                    "configurable": {
                        "thread_id": f"stock_analysis_{code}",
                    },
                },
            )
            messages = result.get("messages", [])
            final_response = (
                messages[-1].content if messages else "分析未能生成结果。"
            )
        except Exception as exc:
            # 降级：仅基本面分析
            return self._fallback_analyze(code, indicators, basic_info, str(exc))

        # 从消息中提取 tool 调用结果
        fundamental_json = None
        technical_json = None
        for msg in messages:
            if isinstance(msg, ToolMessage):
                content = str(msg.content).strip()
                if msg.name == "analyze_fundamentals":
                    parsed = safe_parse_json(content)
                    if isinstance(parsed, dict):
                        fundamental_json = parsed
                elif msg.name == "analyze_technicals":
                    parsed = safe_parse_json(content)
                    if isinstance(parsed, dict) and "error" not in parsed:
                        technical_json = parsed

        # 构建返回 dict
        entry: Dict[str, Any] = {"code": code}

        if fundamental_json:
            entry.update(fundamental_json)
        else:
            # 没有调基本面工具时，填充默认值
            entry.setdefault("overall_score", 50)
            entry.setdefault("rating", "未分析")
            entry.setdefault("summary", final_response)

        # 合并技术面结果
        if technical_json:
            tech_summary = technical_json.pop("summary", {}) if isinstance(technical_json, dict) else {}
            if isinstance(tech_summary, dict):
                entry["technical_analysis"] = {
                    "overall_score": 50,  # 技术面不做评分，仅描述
                    "trend": tech_summary.get("trend", "震荡"),
                    "signals": tech_summary.get("signals", []),
                    "indicators": {
                        k: v for k, v in technical_json.items()
                        if k in {"MACD", "KDJ", "RSI", "BOLL", "MA", "WR"}
                    },
                    "summary": final_response,
                    "risks": tech_summary.get("risks", []),
                }
            else:
                entry["technical_analysis"] = technical_json

        # 确保 summary 有值
        if not entry.get("summary"):
            entry["summary"] = final_response

        # 补全展示用字段
        entry["name"] = basic_info.get("name", code) if isinstance(basic_info, dict) else code
        entry["indicators"] = indicators if isinstance(indicators, dict) else {}
        quote = self.shared_memory.query(f"stock_quote_{code}", {})
        entry["quote"] = quote if isinstance(quote, dict) else {}
        candidate = self.shared_memory.query(f"stock_search_candidate_{code}", {})
        entry["search_candidate"] = candidate if isinstance(candidate, dict) else {}

        # 写入共享内存
        self.shared_memory.publish_fact(
            f"fundamental_analysis_{code}", entry, source=self.agent_name,
        )
        if "technical_analysis" in entry:
            self.shared_memory.publish_fact(
                f"technical_analysis_{code}",
                entry["technical_analysis"],
                source=self.agent_name,
            )

        return entry

    def _fallback_analyze(
        self,
        code: str,
        indicators: Dict[str, Any],
        basic_info: Dict[str, Any],
        error_msg: str = "",
    ) -> Dict[str, Any]:
        """ReAct Agent 执行失败时降级为仅基本面分析（兼容旧行为）。"""
        if not indicators and not basic_info:
            result = {
                "code": code, "rating": "未知", "overall_score": 50,
                "summary": f"分析执行异常{'：' + error_msg if error_msg else ''}",
            }
        else:
            financial_data = {
                "code": code,
                "basic_info": basic_info or {},
                "indicators": indicators or {},
            }
            raw = self._run_fundamental_chain(code, financial_data)
            parsed = safe_parse_json(raw)
            result = parsed if isinstance(parsed, dict) else {
                "code": code, "overall_score": 50, "rating": "中性",
                "summary": "基本面分析解析失败",
            }

        result["code"] = code
        result["overall_score"] = _safe_score(result.get("overall_score"))
        result["name"] = basic_info.get("name", code) if isinstance(basic_info, dict) else code
        result["indicators"] = indicators if isinstance(indicators, dict) else {}
        quote = self.shared_memory.query(f"stock_quote_{code}", {})
        result["quote"] = quote if isinstance(quote, dict) else {}
        candidate = self.shared_memory.query(f"stock_search_candidate_{code}", {})
        result["search_candidate"] = candidate if isinstance(candidate, dict) else {}

        if self.shared_memory:
            self.shared_memory.publish_fact(
                f"fundamental_analysis_{code}", result, source=self.agent_name,
            )
        return result

    def handle(
        self,
        message: str,
        customer_id: str = "",
        chat_history: List[Dict[str, str]] | None = None,
        thread_id: str | None = None,
        memory_context: str = "",
    ) -> str:
        """分析所有关注股票。"""
        if not self.shared_memory:
            return "股票分析需要共享内存支持。"

        stock_codes: list[str] = []
        user_profile = self.shared_memory.query("user_profile", {})
        if isinstance(user_profile, dict):
            stock_codes = user_profile.get("stock_codes", [])

        if not stock_codes:
            return "未识别到需要分析的股票代码。"

        analyses: list[Dict[str, Any]] = [
            self.handle_single_stock(
                code,
                user_message=message,
                memory_context=memory_context,
                chat_history=chat_history,
            )
            for code in stock_codes[:5]
        ]

        parts = [f"已完成 {len(analyses)} 只股票的分析："]
        for a in analyses:
            code = a.get("code", "")
            rating = a.get("rating", "未知")
            score = _safe_score(a.get("overall_score"), 0.0)
            summary = a.get("summary", "")
            tech = a.get("technical_analysis")
            tech_hint = ""
            if isinstance(tech, dict):
                tech_trend = tech.get("trend", "")
                tech_signals = tech.get("signals", [])
                if tech_trend:
                    tech_hint = f" 技术面：{tech_trend}"
                if tech_signals:
                    tech_hint += f" 信号：{'、'.join(tech_signals[:3])}"
            parts.append(
                f"  - {code} 评级：{rating}（{score:.0f}分）"
                f"{tech_hint} | {summary}"
            )

        return "\n".join(parts)
```

- [ ] **Step 3: 验证模块可导入**

Run: `python -c "from finance_agent.agents.stock_analysis import StockAnalysisAgent; print('Import OK')"`

Expected: `Import OK`

- [ ] **Step 4: 验证 agent_name 和基本属性**

Run:
```powershell
python -c "
from finance_agent.agents.stock_analysis import StockAnalysisAgent
agent = StockAnalysisAgent()
print('agent_name:', agent.agent_name)
tools = agent._get_tools()
print('tools count:', len(tools))
print('tool names:', [t.name for t in tools])
"
```

Expected: `agent_name: stock_analysis`, `tools count: 2`, tool names 包含 `analyze_fundamentals` 和 `analyze_technicals`

- [ ] **Step 5: 提交**

```bash
git add finance_agent/agents/stock_analysis.py
git commit -m "feat: refactor FundamentalAnalysisAgent into StockAnalysisAgent

Replace single-purpose fundamental analysis agent with ReAct-based
StockAnalysisAgent that autonomously decides between fundamental and
technical analysis tool calls based on conversation context.

- analyze_fundamentals tool: reuses existing LLM chain for structured
  financial analysis (profitability, growth, valuation, health)
- analyze_technicals tool: computes MACD/KDJ/RSI/BOLL/MA/WR from
  K-line history via technical_indicators module
- ReAct agent receives conversation summary + current question +
  available data description, decides which tools to call
- Falls back to fundamental-only analysis on ReAct failure
- handle() signature unchanged for backward compatibility

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: 更新 agents/__init__.py 导出

**Files:**
- Modify: `finance_agent/agents/__init__.py`

**Interfaces:**
- Produces: exports `StockAnalysisAgent` (替换 `FundamentalAnalysisAgent`)
- Consumes: `stock_analysis.py` StockAnalysisAgent class (Task 3)

- [ ] **Step 1: 修改导入和导出**

`Read` 当前文件内容（已确认在上下文中：第 6 行 `from finance_agent.agents.stock_analysis import FundamentalAnalysisAgent`，第 14 行 `"FundamentalAnalysisAgent"`）。

修改两处：

1. 第 6 行：
```python
from finance_agent.agents.stock_analysis import StockAnalysisAgent
```
（替换 `FundamentalAnalysisAgent`）

2. 第 14 行：
```python
    "StockAnalysisAgent",
```
（替换 `"FundamentalAnalysisAgent"`）

3. 更新文件顶部的 docstring（第 1 行）：
```python
"""Agent 定义 —— 监督者、画像抽取、数据获取、股票分析、资产配置、合规风控。"""
```
（`基本面分析` → `股票分析`）

- [ ] **Step 2: 验证导入**

Run: `python -c "from finance_agent.agents import StockAnalysisAgent; print('StockAnalysisAgent import OK')"`

- [ ] **Step 3: 提交**

```bash
git add finance_agent/agents/__init__.py
git commit -m "refactor: rename FundamentalAnalysisAgent to StockAnalysisAgent in exports

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: 更新 orchestrator.py 引用

**Files:**
- Modify: `finance_agent/core/orchestrator.py`

**Interfaces:**
- Consumes: `StockAnalysisAgent` class (Task 3, 4)
- Modifies: `AdvisorState` TypedDict, `AdvisorSystem.__init__`, `analyze_stock_task`, `fundamental_batch_handler`, `_build_fundamental_summary`

- [ ] **Step 1: 修改导入行**

修改 `orchestrator.py` 第 53 行：
```python
from finance_agent.agents.stock_analysis import StockAnalysisAgent
```
（替换 `FundamentalAnalysisAgent`）

- [ ] **Step 2: 更新文件头 docstring**

修改第 4 行：
```python
- 6 Agent 流水线：监督者 → 画像抽取 → 数据获取 → 股票分析 → 资产配置 → 合规风控
```
（`基本面分析` → `股票分析`）

- [ ] **Step 3: 修改 AdvisorState — 新增 stock_analysis 和 technical_analysis 字段**

在 `AdvisorState` TypedDict 中，将现有第 82 行：
```python
    fundamental_analysis: Dict[str, Any]   # 基本面分析结果（join 节点填充）
```
替换为：
```python
    stock_analysis: Dict[str, Any]             # 股票综合分析结果（join 节点填充）
    technical_analysis: Dict[str, Any]         # 技术面分析结果
```

同时新增 `stock_analysis_entries` 字段，将第 94 行：
```python
    fundamental_entries: List[Dict[str, Any]]
```
替换为：
```python
    stock_analysis_entries: List[Dict[str, Any]]
```

- [ ] **Step 4: 修改 advisor_system.__init__ — 实例化 StockAnalysisAgent**

修改第 129-131 行：
```python
        self.stock_agent = StockAnalysisAgent(
            shared_memory=self.shared_memory, checkpointer=self.checkpointer,
        )
```
（替换 `self.fundamental_agent = FundamentalAnalysisAgent(...)`）

- [ ] **Step 5: 修改 analyze_stock_task — 传递上下文 + 使用新 agent**

修改第 1016-1036 行的 `analyze_stock_task` 函数：

```python
        @task
        def analyze_stock_task(payload: Dict[str, Any]) -> Dict[str, Any]:
            """分析一只股票；输入中的数据先用于恢复共享内存。"""
            code = str(payload["code"])
            stock_item = payload.get("stock_data", {})
            if isinstance(stock_item, dict):
                _publish_stock_entry({"code": code, **stock_item})
            try:
                entry = self.stock_agent.handle_single_stock(
                    code,
                    user_message=str(payload.get("user_message", "")),
                    memory_context=str(payload.get("memory_context", "")),
                )
                entry.setdefault("status", "success")
            except Exception as exc:
                entry = {
                    "code": code,
                    "status": "error",
                    "error": str(exc),
                    "rating": "未知",
                    "summary": "股票分析执行异常",
                    "overall_score": 50,
                }
            entry["code"] = code
            entry["_run_id"] = str(payload.get("run_id", ""))
            return entry
```

- [ ] **Step 6: 修改 fundamental_batch_handler — payload 传上下文**

修改第 1038-1128 行的 `fundamental_batch_handler`。关键改动：

a) 函数重命名为 `stock_analysis_batch_handler`（修改 `def fundamental_batch_handler(state:` → `def stock_analysis_batch_handler(state:`）

b) 修改 trace 和 progress 引用（第 1056-1060 行）：
```python
                self._trace_agent(state, "StockAnalysisAgent", code)
                self._emit_progress(
                    "stock_analysis", f"正在分析 {code}",
                    str(state.get("thread_id", "")),
                )
```

c) payloads 增加 user_message 和 memory_context（修改第 1045-1052 行）：
```python
            payloads = [
                {
                    "code": code,
                    "run_id": state.get("run_id", ""),
                    "stock_data": stock_data.get(code, {}),
                    "user_message": state.get("user_message", ""),
                    "memory_context": state.get("memory_context", ""),
                }
                for code in codes
            ]
```

d) 状态字段名称更新（修改第 1063 和 1079 行）：
```python
            state["stock_analysis_entries"] = entries
            ...
            state["stock_analysis"] = analysis
```

e) 摘要生成函数引用更新（修改第 1084-1086 行）：
```python
                state["agent_response"] = self._build_stock_analysis_summary(
                    analysis, codes, screening=bool(state.get("candidate_stocks"))
                )
```

以及第 1104-1106 行和第 1120-1122 行同样替换 `_build_fundamental_summary` → `_build_stock_analysis_summary`

f) 新增：technical_analysis 聚合（在 `state["stock_analysis"] = analysis` 之后添加）：
```python
            # 聚合技术面分析结果
            tech_analysis: Dict[str, Any] = {}
            for entry in entries:
                if entry.get("_run_id") != state.get("run_id", ""):
                    continue
                code = str(entry.get("code", ""))
                if not code:
                    continue
                tech = entry.get("technical_analysis")
                if isinstance(tech, dict):
                    tech_analysis[code] = tech
            state["technical_analysis"] = tech_analysis
```

- [ ] **Step 7: 重命名 _build_fundamental_summary → _build_stock_analysis_summary 并扩展**

修改第 336 行的方法名和逻辑：
```python
    def _build_stock_analysis_summary(
        self, analysis: Dict[str, Any], codes: List[str], screening: bool = False
    ) -> str:
        """根据股票综合分析结果生成摘要回复。"""
        ...
```

在方法内的每个股票分析块中（`parts.append(f"- **总结**：{summary}")` 之后，`parts.append("")` 之前），添加技术面摘要：

```python
            tech = a.get("technical_analysis")
            if isinstance(tech, dict):
                trend = tech.get("trend", "")
                signals = tech.get("signals", []) or []
                if trend:
                    parts.append(f"- **技术面趋势**：{trend}")
                if signals:
                    parts.append(f"- **技术信号**：{'；'.join(signals[:5])}")
```

同时把标题从 `"## 基本面分析报告"` → `"## 股票分析报告"`（第 354 行）。

- [ ] **Step 8: 更新所有对 fundamental_agent 和 fundamental_analysis 的内部引用**

搜索整个 orchestrator.py 确认这些引用：

Grep for: `fundamental_agent`, `fundamental_analysis`, `fundamental_batch`, `FundamentalAnalysisAgent`, `_fundamental_summary`, `_build_fundamental_summary`, `fundamental_entries`

所有需要替换的映射：
- `self.fundamental_agent` → `self.stock_agent`
- `"fundamental_analysis"` (task_plan 中的步骤名) → 保留不变（orchestrator 外部接口不变）
- `fundamental_batch_handler` → `stock_analysis_batch_handler`
- `"fundamental_batch"` (图节点名) → 保留不变（checkpoint 兼容）
- `FundamentalAnalysisAgent` → `StockAnalysisAgent`（注释/文档字符串中）
- `_build_fundamental_summary` → `_build_stock_analysis_summary`
- `fundamental_entries` → `stock_analysis_entries`

**重要：图中节点名 "fundamental_batch" 保持不变**（第 1280 行的 `graph.add_node("fundamental_batch", fundamental_batch_handler)` 只替换 handler 函数名，不替换节点名）。

额外需修改 `compliance_handler` 中的引用（约第 1222-1224 行）：
```python
            has_verified_analysis = bool(
                state.get("stock_analysis")    # was fundamental_analysis
                or state.get("allocation_result")
                or state.get("stock_data")
            )
```

额外需修改 `handle_message_locked` 返回结果中的字段名（约第 1469 行）：
```python
            "fundamental_analysis": result.get("stock_analysis", {}),
```

- [ ] **Step 9: 更新图中引用**

修改第 1280 行：
```python
        graph.add_node("fundamental_batch", stock_analysis_batch_handler)
```
（handler 名变更，节点名 "fundamental_batch" 保持）

修改第 1321 行：
```python
        graph.add_conditional_edges(
            "fundamental_batch",
            route_after_fundamental,
```
（保持不变，节点名未变）

- [ ] **Step 10: 更新 progress 消息**

搜索 `_emit_progress` 调用中包含 `"fundamental_analysis"` 和 `"正在分析 ... 的基本面"` 的地方：

第 1057-1060 行已在 Step 6 中修改。

- [ ] **Step 11: 更新 _synthesize_response 的注释**

如果发现 `analyze_stock_task` 中对 `self.stock_agent.handle_single_stock` 的调用涉及 `agent_name` 的使用（如共享内存 source），由于 agent_name 从 `"fundamental"` 变为 `"stock_analysis"`，共享内存 source 标签会变，但不影响功能——下游 consumer 通过 key prefix 查找，不通过 source。

- [ ] **Step 12: 验证 orchestrator 可导入**

Run: `python -c "from finance_agent.core.orchestrator import AdvisorSystem; print('Orchestrator import OK')"`

Expected: `Orchestrator import OK`

- [ ] **Step 13: 验证图可以编译**

Run:
```powershell
python -c "
from finance_agent.core.orchestrator import AdvisorSystem
sys = AdvisorSystem()
print('Graph compiled OK, nodes:', list(sys.graph.nodes.keys())[:10])
"
```

Expected: `Graph compiled OK, nodes:` 后跟节点列表

- [ ] **Step 14: 提交**

```bash
git add finance_agent/core/orchestrator.py
git commit -m "feat: integrate StockAnalysisAgent into orchestrator

Replace FundamentalAnalysisAgent with StockAnalysisAgent throughout
the orchestrator. Pass user_message and memory_context to
handle_single_stock for context-aware analysis decisions.

- AdvisorState: add stock_analysis and technical_analysis fields
- analyze_stock_task: pass user_message/memory_context to agent
- fundamental_batch_handler: renamed to stock_analysis_batch_handler
- _build_fundamental_summary: renamed to _build_stock_analysis_summary
  with technical analysis section support
- Graph node name 'fundamental_batch' preserved for checkpoint compat

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: 添加 stock_analysis 温度配置

**Files:**
- Modify: `finance_agent/config.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `AGENT_TEMPERATURES["stock_analysis"]` entry

- [ ] **Step 1: 添加温度配置**

在 `AGENT_TEMPERATURES` 字典（第 94-102 行）中添加：
```python
    "stock_analysis": 0.3,   # 股票综合分析：适度温度保证分析深度与决策灵活性
```

在 `"fundamental": 0.3,` 之后、`"allocation": 0.2,` 之前添加。

- [ ] **Step 2: 验证**

Run: `python -c "from finance_agent.config import AGENT_TEMPERATURES; assert 'stock_analysis' in AGENT_TEMPERATURES; print('OK:', AGENT_TEMPERATURES['stock_analysis'])"`

Expected: `OK: 0.3`

- [ ] **Step 3: 提交**

```bash
git add finance_agent/config.py
git commit -m "feat: add stock_analysis temperature config (0.3)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## 实施顺序

```
Task 1 (technical_indicators.py) ──┐
                                    ├── Task 3 (stock_analysis.py)
Task 2 (tools/__init__.py) ────────┘       │
                                            ├── Task 4 (agents/__init__.py)
                                            │       │
                                            └── Task 5 (orchestrator.py)
                                                    │
                                            Task 6 (config.py, 可并行)
```

Task 1 和 Task 2 可并行。Task 3 依赖 Task 1+2。Task 4 依赖 Task 3。Task 5 依赖 Task 3+4。Task 6 独立，可与 Task 4/5 并行。
