"""资产配置 Agent。

职责：基于MPT计算量化指标，生成资产配置建议
- 年化收益率、年化波动率、夏普比率
- 相关性矩阵
- 均值-方差优化最优权重
- 根据用户风险偏好选择优化目标（最小方差/最大夏普）
- 内置多空辩论模块，对配置方案进行交叉审查

配置结果写入 AdvisorState，供总管汇总。
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional

try:  # AutoGen 不是所有部署环境的必选依赖。
    from autogen import AssistantAgent, GroupChat, GroupChatManager, LLMConfig
except ImportError:  # pragma: no cover - 由未安装 AutoGen 的环境触发
    AssistantAgent = None  # type: ignore[assignment,misc]
    GroupChat = None  # type: ignore[assignment,misc]
    GroupChatManager = None  # type: ignore[assignment,misc]
    LLMConfig = None  # type: ignore[assignment,misc]

from finance_agent.agents.base import ProceduralAgent
from finance_agent.orchestrator.tools.allocation import calculate_stock_metrics, optimize_portfolio


# ── 多空辩论模块（内联，原 finance_agent/debate/coordinator.py）──


@dataclass
class DebateResult:
    """保存辩论过程及其结构化结论。"""

    bull_plan: Dict[str, Any] = field(default_factory=dict)
    bear_challenges: List[str] = field(default_factory=list)
    unresolved_risks: List[str] = field(default_factory=list)
    bull_arguments: List[str] = field(default_factory=list)
    bear_arguments: List[str] = field(default_factory=list)
    disagreements: List[str] = field(default_factory=list)
    convergences: List[str] = field(default_factory=list)
    summary: str = ""
    rationale: str = ""
    status: str = "completed"
    messages: List[Dict[str, str]] = field(default_factory=list)

    # 将结果转换为可写入 AdvisorState 的普通字典。
    def to_dict(self) -> Dict[str, Any]:
        """返回不包含 dataclass 类型的结构化结果。"""
        return asdict(self)


class DebateCoordinator:
    """负责配置 DeepSeek 并执行有轮次、总超时限制的辩论。"""

    # 初始化协调器，允许测试注入 AutoGen 实现和配置值。
    def __init__(
        self,
        max_rounds: Optional[int] = None,
        timeout: Optional[float] = None,
        enabled: Optional[bool] = None,
    ) -> None:
        """读取辩论配置，避免模块导入时强制加载需要 API Key 的 config。"""
        from finance_agent import config

        self.max_rounds = max(1, int(max_rounds if max_rounds is not None else config.DEBATE_MAX_ROUNDS))
        self.timeout = max(0.0, float(timeout if timeout is not None else config.DEBATE_TIMEOUT))
        self.enabled = config.DEBATE_ENABLED if enabled is None else bool(enabled)

    # 构建仅指向 DeepSeek OpenAI 兼容端点的 AutoGen 配置。
    def _build_llm_config(self) -> Any:
        """返回 AutoGen LLMConfig 或兼容旧版 AutoGen 的字典。"""
        from finance_agent import config

        llm_config = {
            "config_list": [{
                "model": "deepseek-chat",
                "api_key": config.DEEPSEEK_API_KEY,
                "base_url": "https://api.deepseek.com/v1",
            }],
            "temperature": config.DEBATE_BULL_TEMPERATURE,
        }
        if LLMConfig is None:
            return llm_config
        try:
            return LLMConfig(**llm_config)
        except TypeError:
            return llm_config

    # 生成 AutoGen 需要的初始辩论提示。
    def _build_prompt(self, context: Dict[str, Any]) -> str:
        """把 MPT、基本面和技术面材料序列化为辩论输入。"""
        return (
            "你正在进行资产配置多空辩论。看多方先提出含权重和成长逻辑的方案，"
            "看空方逐项检查估值、集中度、回撤与宏观风险。材料如下：\n"
            + json.dumps(context or {}, ensure_ascii=False, default=str)
        )

    # 从 AutoGen 的聊天记录中提取可序列化消息。
    def _collect_messages(self, history: Iterable[Any]) -> List[Dict[str, str]]:
        """兼容字典消息和 AutoGen 消息对象。"""
        collected: List[Dict[str, str]] = []
        for item in history or []:
            if isinstance(item, dict):
                role = str(item.get("name") or item.get("role") or "assistant")
                content = str(item.get("content") or "")
            else:
                role = str(getattr(item, "name", None) or getattr(item, "role", None) or "assistant")
                content = str(getattr(item, "content", item) or "")
            if content:
                collected.append({"role": role, "content": content})
        return collected

    # 将聊天记录映射为 DebateResult 的固定字段。
    def _result_from_messages(self, messages: List[Dict[str, str]]) -> DebateResult:
        """按角色收集双方论据，并保留原始消息供上层审计。"""
        bull: List[str] = []
        bear: List[str] = []
        for message in messages:
            role = message["role"].lower()
            if "bull" in role or "看多" in role:
                bull.append(message["content"])
            elif "bear" in role or "看空" in role:
                bear.append(message["content"])
        challenges = bear[:]
        return DebateResult(
            bear_challenges=challenges,
            unresolved_risks=challenges,
            bull_arguments=bull,
            bear_arguments=bear,
            disagreements=challenges,
            convergences=[],
            summary="已完成看多与看空观点交叉审查。",
            rationale="对看空方未被有效反驳的风险标的降低配置权重，其余标的保留 MPT 参考权重。",
            messages=messages,
        )

    # 执行 AutoGen GroupChat，最多产生每轮两方各一次发言。
    def _run_group_chat(self, context: Dict[str, Any]) -> DebateResult:
        """在 AutoGen 不同版本 API 间保持最小兼容。"""
        if AssistantAgent is None or GroupChat is None:
            return DebateResult(status="unavailable")
        llm_config = self._build_llm_config()
        bull = AssistantAgent("debate_bull", system_message="你是看多分析师，先提出配置方案并回应质疑。", llm_config=llm_config)
        bear = AssistantAgent("debate_bear", system_message="你是看空分析师，审查方案并列出未解决风险。", llm_config=llm_config)
        group = GroupChat(agents=[bull, bear], messages=[], max_round=self.max_rounds * 2)
        manager_kwargs = {"groupchat": group, "llm_config": llm_config}
        manager = GroupChatManager(**manager_kwargs) if GroupChatManager is not None else None
        if manager is None:
            return DebateResult(status="unavailable")
        bull.initiate_chat(manager, message=self._build_prompt(context), max_turns=self.max_rounds * 2)
        history = getattr(group, "messages", [])
        return self._result_from_messages(self._collect_messages(history))

    # 在后台线程执行辩论并在总超时后返回。
    def run(self, context: Dict[str, Any]) -> DebateResult:
        """执行辩论；禁用、缺依赖、异常和超时均返回可消费的降级结果。"""
        if not self.enabled:
            return DebateResult(status="disabled")
        result: List[DebateResult] = []
        error: List[BaseException] = []

        # 使用 daemon 线程避免网络调用卡住主流程退出。
        def worker() -> None:
            """在线程中运行 AutoGen，捕获异常交给主线程降级。"""
            try:
                result.append(self._run_group_chat(context))
            except BaseException as exc:  # 任何供应商/版本异常都不能阻塞主流程。
                error.append(exc)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        thread.join(self.timeout)
        if thread.is_alive():
            return DebateResult(status="timeout")
        if error or not result:
            return DebateResult(status="error")
        return result[0]


# 提供模块级入口，供资产配置专家和测试直接调用。
def run_debate(context: Dict[str, Any]) -> DebateResult:
    """使用默认配置执行一场 DeepSeek-only 多空辩论。"""
    try:
        return DebateCoordinator().run(context)
    except Exception:
        return DebateResult(status="error")


# ── 资产配置 Agent ──


_ASSET_ALLOCATION_PROMPT = """你是资产配置专家。

## 身份
你负责基于现代投资组合理论(MPT)为用户生成资产配置建议。

## 工作流程
1. 使用传入的用户画像、历史行情和基本面分析数据
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
- 语言要求：使用正式、专业的书面中文。不得使用口语化的表述。
  配置理由应基于指标数值与风险收益特征进行严谨阐述，如"标的A的夏普比率
  显著高于标的B，且历史波动率较低，因此配置权重偏向标的A"。
"""


class AssetAllocationAgent(ProceduralAgent):
    """资产配置 Agent。"""

    agent_name: str = "allocation"

    def build_business_state(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        """校验生成个人配置方案所需的画像字段。"""
        required_fields = {
            "stock_codes": {"prompt": "至少提供2只A股股票名称或六位代码"},
            "risk_preference": {"prompt": "说明风险偏好（保守、稳健、平衡或进取）"},
            "budget_amount": {"prompt": "说明投资预算金额（元）"},
            "holding_period": {"prompt": "说明预期持有时间"},
        }
        missing = [
            field for field in required_fields
            if not (profile or {}).get(field)
        ]
        return {
            "agent": self.agent_name,
            "status": "waiting_for_input" if missing else "ready",
            "required_fields": required_fields,
            "missing_fields": missing,
        }

    def build_missing_fields_response(self, business_state: Dict[str, Any]) -> str:
        """根据业务状态一次性生成全部缺失字段的引导语。"""
        required = business_state.get("required_fields", {}) or {}
        missing = business_state.get("missing_fields", []) or []
        prompts = [
            str(required.get(field, {}).get("prompt", "")).strip()
            for field in missing
        ]
        prompts = [p for p in prompts if p]
        if not prompts:
            return "继续执行前，请补充必要的业务信息。"
        return "继续执行前，请补充以下信息：\n" + "\n".join(
            f"- {prompt}" for prompt in prompts
        )

    def _get_tools(self) -> list:
        return [calculate_stock_metrics, optimize_portfolio]

    def _get_system_prompt(self) -> str:
        return _ASSET_ALLOCATION_PROMPT

    def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """从 AdvisorState 读取画像和历史数据，执行资产配置并写回结果。"""
        profile = state.get("user_profile", {}) or {}
        stock_data = state.get("stock_data", {}) or {}

        stock_analysis = state.get("stock_analysis", {}) or {}
        response = self._generate_allocation_report(
            profile, state.get("user_message", ""), stock_data, stock_analysis,
        )
        state["agent_response"] = response
        state["allocation_result"] = getattr(self, "_last_allocation_result", {}) or {}
        state["debate_result"] = getattr(self, "_last_debate_result", {}) or {}
        state.setdefault("intent_results", {})["asset_allocation"] = {
            "status": "success" if "失败" not in response and "不足" not in response else "degraded",
            "content": response,
        }
        return state

    def handle(
        self,
        message: str = "",
        user_profile: Dict[str, Any] | None = None,
        stock_data: Dict[str, Any] | None = None,
        stock_analysis: Dict[str, Any] | None = None,
        **_: Any,
    ) -> str:
        """使用显式状态数据生成 MPT 配置报告。"""
        return self._generate_allocation_report(
            user_profile or {}, message, stock_data, stock_analysis,
        )

    def _arbitrate_allocation(
        self,
        allocation: Dict[str, Any],
        debate: Dict[str, Any],
    ) -> None:
        """根据看空方明确指出的标的风险，审慎调整 MPT 权重。"""
        weights = allocation.get("weights", {})
        risks = debate.get("unresolved_risks", []) or []
        if not isinstance(weights, dict) or not isinstance(risks, list):
            return
        risk_text = " ".join(str(item) for item in risks)
        impacted_codes = [
            str(code) for code in weights
            if str(code) in risk_text
        ]
        if not impacted_codes:
            return
        for code in impacted_codes:
            weights[code] = max(0.0, float(weights[code]) * 0.8)
        total = sum(float(value) for value in weights.values())
        if total <= 0:
            return
        allocation["weights"] = {
            code: float(value) / total for code, value in weights.items()
        }
        budget = float(allocation.get("budget", 0) or 0)
        if budget > 0:
            allocation["allocation_amounts"] = {
                code: weight * budget
                for code, weight in allocation["weights"].items()
            }

    def _generate_allocation_report(
        self,
        user_profile: Dict[str, Any],
        message: str = "",
        stock_data: Dict[str, Any] | None = None,
        stock_analysis: Dict[str, Any] | None = None,
    ) -> str:
        """从显式状态读取数据，执行MPT资产配置并生成建议。"""
        profile = user_profile or {}
        if not isinstance(profile, dict):
            profile = {}
        self._last_allocation_result = {}
        self._last_debate_result = {}

        stock_codes = profile.get("stock_codes", [])
        risk_preference = profile.get("risk_preference", "R3 中风险")
        budget = float(profile.get("budget_amount", 0) or 0)

        stock_data = stock_data or {}
        stock_names: dict[str, str] = {}
        for code in stock_codes[:5]:
            item = stock_data.get(code, {}) if isinstance(stock_data, dict) else {}
            basic_info = item.get("basic_info", {}) if isinstance(item, dict) else {}
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

        # 从显式状态收集历史数据
        history_list: list[dict] = []
        for code in stock_codes[:5]:
            item = stock_data.get(code, {}) if isinstance(stock_data, dict) else {}
            hist = item.get("history", {}) if isinstance(item, dict) else {}
            if hist and "error" not in hist:
                history_list.append({"code": code, **hist})

        if len(history_list) < 2:
            failures = []
            for code in stock_codes[:5]:
                item = stock_data.get(code, {}) if isinstance(stock_data, dict) else {}
                hist = item.get("history", {}) if isinstance(item, dict) else {}
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
        stock_codes_str = ",".join([h.get("code", "") for h in history_list])
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

        # 返回结构化配置结果，由编排器写回 AdvisorState。
        allocation["stock_names"] = stock_names
        allocation["budget"] = budget
        debate_context = {
            "user_profile": profile,
            "stock_data": stock_data,
            "stock_analysis": stock_analysis or {},
            "metrics": metrics,
            "allocation": allocation,
        }
        debate_result = run_debate(debate_context)
        debate = debate_result.to_dict() if hasattr(debate_result, "to_dict") else dict(debate_result or {})
        debate_status = str(debate.get("status", "completed"))
        if debate_status == "completed":
            self._arbitrate_allocation(allocation, debate)
            allocation["debate"] = debate
        self._last_allocation_result = allocation
        self._last_debate_result = debate

        # 生成配置建议报告
        parts = ["## 资产配置建议", ""]
        parts.append(f"**风险偏好**：{risk_preference}")
        if budget > 0:
            parts.append(f"**投资预算**：{budget:,.0f} 元")
        parts.append(f"**配置标的**：{stock_codes_str}")
        parts.append("")

        parts.append("### 配置权重")
        weights = allocation.get("weights", {})
        amounts = allocation.get("allocation_amounts", {})
        for code, weight in weights.items():
            pct = float(weight) * 100
            line = f"- {stock_label(code)}：{pct:.1f}%"
            if code in amounts:
                line += f"（{float(amounts[code]):,.0f} 元）"
            parts.append(line)
        parts.append("")

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
        if debate_status == "completed":
            parts.append("### 辩论摘要")
            parts.append(debate.get("summary", "已完成多空观点交叉审查。"))
            parts.append("### 仲裁理由")
            parts.append(debate.get("rationale", "结合未解决风险对相关权重进行审慎调整。"))
        else:
            parts.append("### 辩论状态")
            status_text = {
                "disabled": "辩论未执行，以上配置直接采用 MPT 参考结果。",
                "timeout": "辩论超时，以上配置回退至 MPT 参考结果。",
                "unavailable": "辩论组件不可用，以上配置回退至 MPT 参考结果。",
                "error": "辩论执行失败，以上配置回退至 MPT 参考结果。",
            }.get(debate_status, "辩论未完成，以上配置回退至 MPT 参考结果。")
            parts.append(status_text)
        parts.append("")

        parts.append("### 风险提示")
        parts.append("投资有风险，过往业绩不代表未来收益，请谨慎决策。")
        parts.append("以上配置基于历史数据计算，市场环境变化可能影响实际表现。")

        return "\n".join(parts)
