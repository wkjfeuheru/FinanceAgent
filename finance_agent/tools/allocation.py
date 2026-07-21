"""资产配置计算工具。

基于现代投资组合理论(MPT)计算量化指标和最优配置权重。
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from langchain_core.tools import tool
from scipy.optimize import minimize


def _json(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _extract_close_prices(history_json: str, stock_code: str) -> pd.Series:
    """从历史数据JSON中提取收盘价序列。"""
    try:
        data = json.loads(history_json) if isinstance(history_json, str) else history_json
    except (json.JSONDecodeError, TypeError):
        return pd.Series(dtype=float)

    records = data.get("data", []) if isinstance(data, dict) else []
    if not records:
        return pd.Series(dtype=float)

    df = pd.DataFrame(records)
    if "close" not in df.columns or "date" not in df.columns:
        return pd.Series(dtype=float)

    df = df.sort_values("date").reset_index(drop=True)
    return pd.to_numeric(df["close"], errors="coerce").dropna().reset_index(drop=True)


@tool
def calculate_stock_metrics(stock_codes: str, history_data: str) -> str:
    """计算多只股票的年化收益率、年化波动率、相关性矩阵和夏普比率。

    Args:
        stock_codes: 股票代码列表，逗号分隔，如 "600519,000001,600036"
        history_data: JSON数组，每个元素为单只股票的历史数据JSON（get_stock_history返回值），
                     逗号分隔对应每只股票

    Returns:
        JSON 字符串，包含各股票指标和相关性矩阵
    """
    codes = [c.strip() for c in stock_codes.split(",") if c.strip()]
    # history_data 按逗号分割为各股票的JSON（简化处理：直接用 || 分隔）
    # 实际使用时，Agent会传入合并后的JSON数组
    try:
        all_data = json.loads(history_data) if isinstance(history_data, str) else history_data
        if not isinstance(all_data, list):
            all_data = [all_data]
    except (json.JSONDecodeError, TypeError):
        return _json({"error": "历史数据格式错误", "stock_codes": codes})

    # 提取各股票收盘价
    price_series: dict[str, pd.Series] = {}
    for i, code in enumerate(codes):
        if i < len(all_data):
            prices = _extract_close_prices(all_data[i], code)
            if not prices.empty:
                price_series[code] = prices

    if len(price_series) < 1:
        return _json({"error": "未获取到有效历史数据", "stock_codes": codes})

    # 对齐长度
    min_len = min(len(s) for s in price_series.values())
    aligned = {code: s.iloc[-min_len:].reset_index(drop=True) for code, s in price_series.items()}

    # 计算日收益率
    returns_df = pd.DataFrame(aligned)
    daily_returns = returns_df.pct_change().dropna()

    # 年化指标（252个交易日）
    trading_days = 252
    annual_returns = {}
    annual_volatilities = {}
    for code in daily_returns.columns:
        annual_returns[code] = float(daily_returns[code].mean() * trading_days)
        annual_volatilities[code] = float(daily_returns[code].std() * np.sqrt(trading_days))

    # 夏普比率（无风险利率2%）
    risk_free_rate = 0.02
    sharpe_ratios = {}
    for code in daily_returns.columns:
        if annual_volatilities[code] > 0:
            sharpe_ratios[code] = float(
                (annual_returns[code] - risk_free_rate) / annual_volatilities[code]
            )
        else:
            sharpe_ratios[code] = 0.0

    # 相关性矩阵
    correlation_matrix = {}
    if len(daily_returns.columns) > 1:
        corr = daily_returns.corr()
        for code in corr.columns:
            correlation_matrix[code] = {k: float(v) for k, v in corr[code].items()}

    result = {
        "stock_codes": list(price_series.keys()),
        "annual_returns": {k: round(v, 4) for k, v in annual_returns.items()},
        "annual_volatilities": {k: round(v, 4) for k, v in annual_volatilities.items()},
        "sharpe_ratios": {k: round(v, 4) for k, v in sharpe_ratios.items()},
        "correlation_matrix": correlation_matrix,
        "risk_free_rate": risk_free_rate,
    }
    return _json(result)


@tool
def optimize_portfolio(
    stock_codes: str,
    history_data: str,
    risk_level: str,
    budget: float = 0.0,
) -> str:
    """基于MPT均值-方差优化计算最优资产配置权重。

    根据用户风险偏好选择最优组合：
    - 低风险(R1/R2)：最小方差组合
    - 高风险(R3-R5)：最大夏普比率组合

    Args:
        stock_codes: 股票代码列表，逗号分隔
        history_data: JSON数组，各股票历史数据
        risk_level: 用户风险偏好 R1-R5
        budget: 投资预算（元），用于计算各标的配置金额

    Returns:
        JSON 字符串，包含各股票权重、预期收益、波动率、夏普比率
    """
    codes = [c.strip() for c in stock_codes.split(",") if c.strip()]
    if len(codes) < 2:
        return _json({"error": "至少需要2只股票才能进行组合优化", "stock_codes": codes})

    # 复用 calculate_stock_metrics 的计算
    metrics_json = calculate_stock_metrics.invoke({
        "stock_codes": stock_codes,
        "history_data": history_data,
    })

    try:
        metrics = json.loads(metrics_json)
    except json.JSONDecodeError:
        return _json({"error": "指标计算失败"})

    if "error" in metrics:
        return _json(metrics)

    valid_codes = metrics.get("stock_codes", [])
    if len(valid_codes) < 2:
        return _json({"error": "有效股票数量不足"})

    # 提取年化收益率和波动率
    ann_returns = np.array([metrics["annual_returns"][c] for c in valid_codes])
    ann_vols = np.array([metrics["annual_volatilities"][c] for c in valid_codes])

    # 重新提取价格序列计算协方差矩阵
    try:
        all_data = json.loads(history_data) if isinstance(history_data, str) else history_data
        if not isinstance(all_data, list):
            all_data = [all_data]
    except (json.JSONDecodeError, TypeError):
        return _json({"error": "历史数据格式错误"})

    price_series: dict[str, pd.Series] = {}
    for i, code in enumerate(valid_codes):
        if i < len(all_data):
            prices = _extract_close_prices(all_data[i], code)
            if not prices.empty:
                price_series[code] = prices

    if len(price_series) < 2:
        return _json({"error": "价格数据不足"})

    min_len = min(len(s) for s in price_series.values())
    aligned = {code: s.iloc[-min_len:].reset_index(drop=True) for code, s in price_series.items()}
    returns_df = pd.DataFrame(aligned)
    daily_returns = returns_df.pct_change().dropna()

    trading_days = 252
    cov_matrix = daily_returns.cov().values * trading_days

    n = len(valid_codes)
    risk_free_rate = 0.02

    def portfolio_variance(weights):
        return np.dot(weights.T, np.dot(cov_matrix, weights))

    def portfolio_return(weights):
        return np.sum(ann_returns * weights)

    def negative_sharpe(weights):
        ret = portfolio_return(weights)
        vol = np.sqrt(portfolio_variance(weights))
        if vol == 0:
            return 0
        return -(ret - risk_free_rate) / vol

    # 约束：权重和=1
    constraints = {"type": "eq", "fun": lambda x: np.sum(x) - 1}
    # 边界：0 <= weight <= 0.6（单只不超过60%）
    bounds = tuple((0, 0.6) for _ in range(n))
    x0 = np.array([1.0 / n] * n)

    # 根据风险等级选择优化目标
    risk_num = 3
    for level in ["R1", "R2", "R3", "R4", "R5"]:
        if level.lower() in (risk_level or "").lower():
            risk_num = int(level[1])
            break

    if risk_num <= 2:
        # 低风险：最小方差
        result = minimize(portfolio_variance, x0, method="SLSQP", bounds=bounds, constraints=constraints)
    else:
        # 高风险：最大夏普
        result = minimize(negative_sharpe, x0, method="SLSQP", bounds=bounds, constraints=constraints)

    if not result.success:
        return _json({"error": f"优化失败：{result.message}"})

    optimal_weights = result.x
    exp_return = float(portfolio_return(optimal_weights))
    exp_volatility = float(np.sqrt(portfolio_variance(optimal_weights)))
    sharpe = float((exp_return - risk_free_rate) / exp_volatility) if exp_volatility > 0 else 0

    weights_dict = {code: round(float(w), 4) for code, w in zip(valid_codes, optimal_weights)}

    # 配置金额
    allocation_amounts = {}
    if budget > 0:
        for code, w in zip(valid_codes, optimal_weights):
            allocation_amounts[code] = round(float(budget * w), 2)

    output = {
        "weights": weights_dict,
        "expected_return": round(exp_return, 4),
        "expected_volatility": round(exp_volatility, 4),
        "sharpe_ratio": round(sharpe, 4),
        "risk_free_rate": risk_free_rate,
        "optimization_target": "min_variance" if risk_num <= 2 else "max_sharpe",
    }
    if allocation_amounts:
        output["budget"] = float(budget)
        output["allocation_amounts"] = allocation_amounts

    return _json(output)
