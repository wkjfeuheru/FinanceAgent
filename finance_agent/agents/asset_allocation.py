"""资产配置 Agent。

职责：基于MPT计算量化指标，生成资产配置建议
- 年化收益率、年化波动率、夏普比率
- 相关性矩阵
- 均值-方差优化最优权重
- 根据用户风险偏好选择优化目标（最小方差/最大夏普）

配置结果写入共享内存供合规审查。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from finance_agent.agents.base import BaseFinanceAgent
from finance_agent.tools.allocation import calculate_stock_metrics, optimize_portfolio


_ASSET_ALLOCATION_PROMPT = """你是资产配置专家。

## 身份
你负责基于现代投资组合理论(MPT)为用户生成资产配置建议。

## 工作流程
1. 从共享上下文读取用户画像（股票代码、风险偏好、预算）
2. 调用 calculate_stock_metrics 计算收益率、波动率、相关性
3. 调用 optimize_portfolio 进行MPT优化，获取最优权重
4. 生成配置建议报告

## 配置原则
- 低风险用户(R1/R2)：偏向最小方差组合，波动率优先
- 高风险用户(R3-R5)：偏向最大夏普比率，收益风险比优先
- 单只股票权重不超过60%
- 必须包含风险提示

## 输出要求
- 列出各股票配置权重和金额
- 说明预期收益、波动率、夏普比率
- 结合基本面分析结果给出配置理由
- 必须包含免责声明："投资有风险，过往业绩不代表未来收益，请谨慎决策"
"""


class AssetAllocationAgent(BaseFinanceAgent):
    """资产配置 Agent。"""

    agent_name: str = "allocation"

    def _get_tools(self) -> list:
        return [calculate_stock_metrics, optimize_portfolio]

    def _get_system_prompt(self) -> str:
        return _ASSET_ALLOCATION_PROMPT

    def handle(
        self,
        message: str,
        compressed_context: str = "",
        customer_id: str = "",
        chat_history: List[Dict[str, str]] | None = None,
        thread_id: str | None = None,
        memory_context: str = "",
    ) -> str:
        """执行MPT资产配置并生成建议。"""
        if not self.shared_memory:
            return "资产配置需要共享内存支持。"

        # 从共享内存读取用户画像
        user_profile = self.shared_memory.query("user_profile", {})
        if not isinstance(user_profile, dict):
            user_profile = {}

        stock_codes = user_profile.get("stock_codes", [])
        risk_preference = user_profile.get("risk_preference", "R3 中风险")
        budget = float(user_profile.get("budget_amount", 0) or 0)

        stock_names: dict[str, str] = {}
        for code in stock_codes[:5]:
            basic_info = self.shared_memory.query(f"stock_basic_info_{code}", {}) or {}
            if isinstance(basic_info, dict) and basic_info.get("name"):
                stock_names[code] = str(basic_info["name"]).strip()

        def stock_label(code: str) -> str:
            name = stock_names.get(code, "")
            return f"{name}（{code}）" if name else code

        if len(stock_codes) < 2:
            if not stock_codes:
                return "未识别到股票代码，请提供A股代码（如600519、000001）以便进行资产配置。"
            return (
                f"资产配置至少需要2只股票，当前仅识别到：{','.join(stock_codes)}。"
                "请提供更多股票代码。"
            )

        # 从共享内存收集历史数据
        history_list: list[dict] = []
        for code in stock_codes[:5]:
            hist = self.shared_memory.query(f"stock_history_{code}", {})
            if hist and "error" not in hist:
                history_list.append(hist)

        if len(history_list) < 2:
            # 收集失败的股票和错误原因
            failures = []
            for code in stock_codes[:5]:
                hist = self.shared_memory.query(f"stock_history_{code}", {})
                if not hist:
                    failures.append(f"{code}: 未获取数据")
                elif "error" in hist:
                    failures.append(f"{code}: {hist['error']}")
            failure_detail = "；".join(failures) if failures else "未知原因"
            return (
                f"历史数据不足，无法进行组合优化。失败原因：{failure_detail}。"
                "请检查网络/代理设置后重试，或提供更多股票代码。"
            )

        # 调用工具计算指标
        stock_codes_str = ",".join([h.get("code", code) for h, code in zip(history_list, stock_codes)][:len(history_list)])
        history_json = json.dumps(history_list, ensure_ascii=False, default=str)

        metrics_raw = calculate_stock_metrics.invoke({
            "stock_codes": stock_codes_str,
            "history_data": history_json,
        })

        try:
            metrics = json.loads(metrics_raw) if isinstance(metrics_raw, str) else metrics_raw
        except json.JSONDecodeError:
            metrics = {"error": "指标计算失败"}

        if "error" in metrics:
            return f"指标计算失败：{metrics['error']}"

        # 调用MPT优化
        optimization_raw = optimize_portfolio.invoke({
            "stock_codes": stock_codes_str,
            "history_data": history_json,
            "risk_level": risk_preference,
            "budget": budget,
        })

        try:
            allocation = json.loads(optimization_raw) if isinstance(optimization_raw, str) else optimization_raw
        except json.JSONDecodeError:
            allocation = {"error": "优化失败"}

        if "error" in allocation:
            return f"组合优化失败：{allocation['error']}"

        # 写入共享内存
        allocation["stock_names"] = stock_names
        self.shared_memory.publish_fact("allocation_result", allocation, source=self.agent_name)

        # 计算接口继续使用纯代码；展示阶段改为“名称（代码）”。
        stock_codes_str = "、".join(
            stock_label(code) for code in stock_codes_str.split(",") if code
        )

        # 生成配置建议报告
        parts = ["## 资产配置建议", ""]

        # 用户画像
        parts.append(f"**风险偏好**：{risk_preference}")
        if budget > 0:
            parts.append(f"**投资预算**：{budget:,.0f} 元")
        parts.append(f"**配置标的**：{stock_codes_str}")
        parts.append("")

        # 配置明细
        parts.append("### 配置权重")
        weights = allocation.get("weights", {})
        amounts = allocation.get("allocation_amounts", {})
        for code, weight in weights.items():
            pct = float(weight) * 100
            line = f"- **{code}**：{pct:.1f}%"
            if code in amounts:
                line += f"（{float(amounts[code]):,.0f} 元）"
            line = line.replace(f"**{code}**", f"**{stock_label(code)}**")
            parts.append(line)
        parts.append("")

        # 预期指标
        parts.append("### 预期表现")
        exp_ret = allocation.get("expected_return", 0)
        exp_vol = allocation.get("expected_volatility", 0)
        sharpe = allocation.get("sharpe_ratio", 0)
        parts.append(f"- 预期年化收益率：{float(exp_ret)*100:.2f}%")
        parts.append(f"- 预期年化波动率：{float(exp_vol)*100:.2f}%")
        parts.append(f"- 夏普比率：{float(sharpe):.3f}")
        target = allocation.get("optimization_target", "max_sharpe")
        parts.append(f"- 优化目标：{'最小方差' if target == 'min_variance' else '最大夏普比率'}")
        parts.append("")

        # 各股票指标
        parts.append("### 标的指标")
        ann_returns = metrics.get("annual_returns", {})
        ann_vols = metrics.get("annual_volatilities", {})
        sharpe_ratios = metrics.get("sharpe_ratios", {})
        for code in ann_returns:
            parts.append(
                f"- {code}：年化收益 {float(ann_returns[code])*100:.2f}%，"
                f"波动率 {float(ann_vols.get(code, 0))*100:.2f}%，"
                f"夏普 {float(sharpe_ratios.get(code, 0)):.3f}"
            )
        parts.append("")

        # 免责声明
        parts.append("### 风险提示")
        parts.append("投资有风险，过往业绩不代表未来收益，请谨慎决策。")
        parts.append("以上配置基于历史数据计算，市场环境变化可能影响实际表现。")

        return "\n".join(parts)
