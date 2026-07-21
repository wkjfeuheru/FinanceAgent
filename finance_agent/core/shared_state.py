"""Agent 共享工作内存 —— 实现 Agent 间信息共享。
核心设计：
- facts: 已确认的事实，任何 Agent 可读写
- hypotheses: 待验证的假设
- messages: Agent 间通信消息队列
- contradictions: 冲突标记，触发仲裁

这是从"Agent 隔离"到"Agent 协作"的关键基础设施。
"""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class AgentMessage:
    """Agent 间通信消息。"""

    sender: str
    receiver: str | None  # None = 广播
    msg_type: str  # "finding", "question", "suggestion", "warning"
    content: Dict[str, Any]
    priority: int = 0


class SharedWorkingMemory:
    """Agent 间的共享工作内存。

    设计原则：
    1. 发布-订阅模式：Agent 可以发布发现，其他 Agent 可以查询
    2. 冲突检测：如果两个 Agent 对同一事实有不同看法，自动标记冲突
    3. 分层存储：事实（已确认）、假设（待验证）、冲突（需仲裁）
    4. 线程安全：使用 RLock 保护所有读写操作，支持 LangGraph Send 并行节点
    """

    def __init__(self):
        # 已确认的事实 —— 所有 Agent 可信任的信息
        self.facts: Dict[str, Any] = {}

        # 待验证的假设 —— 需要其他 Agent 确认
        self.hypotheses: Dict[str, Any] = {}

        # 冲突标记 —— 两个 Agent 意见不一致时需要仲裁
        self.contradictions: Dict[str, Dict[str, Any]] = {}

        # 消息历史
        self.messages: List[AgentMessage] = []

        # 订阅关系
        self.subscriptions: Dict[str, List[str]] = defaultdict(list)

        # 会话统计
        self.stats: Dict[str, int] = defaultdict(int)

        # 可重入锁：publish_fact 内部调用 publish，需可重入
        self._lock = threading.RLock()

    # ── 发布 / 订阅 ──────────────────────────────────────────

    def publish(self, message: AgentMessage) -> None:
        """Agent 发布一条消息。

        - 广播消息（receiver=None）会通知所有订阅者
        - 定向消息（receiver="agent_name"）只通知指定 Agent
        - finding 类型的消息自动写入 facts
        """
        with self._lock:
            self.messages.append(message)
            self.stats["total_messages"] += 1

            if message.msg_type == "finding":
                key = message.content.get("key", "")
                if key:
                    # 冲突检测
                    if key in self.facts:
                        existing = self.facts[key]
                        if existing != message.content.get("value"):
                            self.contradictions[key] = {
                                "claim_a": existing,
                                "claim_b": message.content.get("value"),
                                "agent_a": self.facts.get(f"{key}__source", "unknown"),
                                "agent_b": message.sender,
                                "resolved": False,
                            }
                            message.msg_type = "warning"
                            message.content["warning"] = "与已有事实冲突"

                    self.facts[key] = message.content.get("value")
                    self.facts[f"{key}__source"] = message.sender
                    self.stats["facts_published"] += 1

    def publish_fact(self, key: str, value: Any, source: str = "unknown") -> None:
        """便捷方法：直接发布一个事实。"""
        self.publish(AgentMessage(
            sender=source,
            receiver=None,
            msg_type="finding",
            content={"key": key, "value": value},
        ))

    def subscribe(self, topic: str, agent_name: str) -> None:
        """Agent 订阅某个主题，当该主题有新发现时会收到通知。"""
        with self._lock:
            self.subscriptions[topic].append(agent_name)

    def get_subscribers(self, topic: str) -> List[str]:
        """获取某主题的订阅者列表。"""
        with self._lock:
            return list(self.subscriptions.get(topic, []))

    # ── 查询接口 ─────────────────────────────────────────────

    def query(self, key: str, default: Any = None) -> Any:
        """查询已确认的事实。"""
        with self._lock:
            return self.facts.get(key, default)

    def query_prefix(self, prefix: str) -> Dict[str, Any]:
        """按前缀查询事实（如 query_prefix('mentioned_product_') 获取所有产品引用）。"""
        with self._lock:
            return {k: v for k, v in self.facts.items() if k.startswith(prefix)}

    def has_fact(self, key: str) -> bool:
        """检查事实是否已存在。"""
        with self._lock:
            return key in self.facts

    def get_fact_source(self, key: str) -> str:
        """获取事实的来源 Agent。"""
        with self._lock:
            return self.facts.get(f"{key}__source", "unknown")

    # ── 假设管理 ─────────────────────────────────────────────

    def propose_hypothesis(self, key: str, value: Any, proposer: str) -> None:
        """提出一个待验证的假设。"""
        with self._lock:
            self.hypotheses[key] = {
                "value": value,
                "proposer": proposer,
                "status": "pending",
                "confirmers": [],
                "refuters": [],
            }

    def confirm_hypothesis(self, key: str, confirmer: str) -> None:
        """确认一个假设。"""
        with self._lock:
            if key in self.hypotheses:
                self.hypotheses[key]["confirmers"].append(confirmer)
                if len(self.hypotheses[key]["confirmers"]) >= 2:
                    # 两个 Agent 确认 → 升级为事实
                    self.publish_fact(key, self.hypotheses[key]["value"], "consensus")
                    self.hypotheses[key]["status"] = "confirmed"

    def refute_hypothesis(self, key: str, refuter: str, reason: str = "") -> None:
        """反驳一个假设。"""
        with self._lock:
            if key in self.hypotheses:
                self.hypotheses[key]["refuters"].append({"agent": refuter, "reason": reason})
                self.hypotheses[key]["status"] = "refuted"

    # ── 冲突管理 ─────────────────────────────────────────────

    def has_contradictions(self) -> bool:
        """检查是否有未解决的冲突。"""
        with self._lock:
            return any(not c.get("resolved", False) for c in self.contradictions.values())

    def get_unresolved_contradictions(self) -> Dict[str, Dict[str, Any]]:
        """获取所有未解决的冲突。"""
        with self._lock:
            return {
                k: v for k, v in self.contradictions.items()
                if not v.get("resolved", False)
            }

    def resolve_contradiction(self, key: str, winner: str, reason: str = "") -> None:
        """仲裁解决一个冲突。"""
        with self._lock:
            if key in self.contradictions:
                self.contradictions[key]["resolved"] = True
                self.contradictions[key]["winner"] = winner
                self.contradictions[key]["reason"] = reason

    # ── 格式化工具 ───────────────────────────────────────────

    def format_facts_for_prompt(self, prefix_filter: str | None = None) -> str:
        """将共享工作内存中的事实格式化为人类可读的提示词片段。

        用于注入到 Agent 上下文，让 Agent 直接引用这些数据回答用户问题。
        输出为自然语言格式，适配金融投顾场景。
        """
        # 取快照后释放锁，避免格式化期间长时间持锁
        with self._lock:
            if prefix_filter:
                facts_to_show = {
                    k: v for k, v in self.facts.items()
                    if k.startswith(prefix_filter) and not k.endswith("__source")
                }
            else:
                facts_to_show = dict(self.facts)

        if not facts_to_show:
            return ""

        # ── 分组提取投顾数据 ──
        user_profile: dict = {}
        quotes: list[dict] = []
        histories: list[dict] = []
        indicators: list[dict] = []
        basic_infos: list[dict] = []
        fundamentals: list[dict] = []
        allocation: dict = {}

        for key, value in facts_to_show.items():
            if key.endswith("__source"):
                continue
            if key == "user_profile":
                user_profile = value if isinstance(value, dict) else {}
            elif key.startswith("stock_quote_"):
                if isinstance(value, dict):
                    quotes.append(value)
            elif key.startswith("stock_history_"):
                if isinstance(value, dict):
                    histories.append(value)
            elif key.startswith("financial_indicator_"):
                if isinstance(value, dict):
                    indicators.append(value)
            elif key.startswith("stock_basic_info_"):
                if isinstance(value, dict):
                    basic_infos.append(value)
            elif key.startswith("fundamental_analysis_"):
                if isinstance(value, dict):
                    fundamentals.append(value)
            elif key == "allocation_result":
                allocation = value if isinstance(value, dict) else {}

        # 隔离同一会话以前分析过的股票，只展示当前画像中的标的。
        active_codes = set(user_profile.get("stock_codes", [])) if user_profile else set()
        if active_codes:
            quotes = [x for x in quotes if x.get("code") in active_codes]
            histories = [x for x in histories if x.get("code") in active_codes]
            indicators = [x for x in indicators if x.get("code") in active_codes]
            basic_infos = [x for x in basic_infos if x.get("code") in active_codes]
            fundamentals = [x for x in fundamentals if x.get("code") in active_codes]

        # ── 自然语言输出 ──
        parts = []

        if user_profile:
            lines = ["用户画像："]
            if user_profile.get("risk_preference"):
                lines.append(f"  风险偏好：{user_profile['risk_preference']}")
            if user_profile.get("budget_amount"):
                lines.append(f"  预算金额：{float(user_profile['budget_amount']):,.0f} 元")
            if user_profile.get("stock_codes"):
                lines.append(f"  关注股票：{', '.join(user_profile['stock_codes'])}")
            if user_profile.get("holding_period"):
                lines.append(f"  持有时间：{user_profile['holding_period']}")
            if user_profile.get("investment_goal"):
                lines.append(f"  投资目标：{user_profile['investment_goal']}")
            parts.append("\n".join(lines))

        if basic_infos:
            lines = ["股票基本信息："]
            for info in basic_infos:
                code = info.get("code", "")
                name = info.get("name", "")
                industry = info.get("industry", "")
                lines.append(f"  - {code}「{name}」行业：{industry}")
            parts.append("\n".join(lines))

        if quotes:
            lines = ["实时行情："]
            for q in quotes:
                code = q.get("code", "")
                name = q.get("name", "")
                price = q.get("price", 0)
                change_pct = q.get("change_pct", 0)
                lines.append(f"  - {code}「{name}」最新价：{price:.2f} 涨跌幅：{change_pct:+.2f}%")
            parts.append("\n".join(lines))

        if indicators:
            lines = ["财务指标："]
            for ind in indicators:
                code = ind.get("code", "")
                pe = ind.get("pe", 0)
                pb = ind.get("pb", 0)
                roe = ind.get("roe", 0)
                lines.append(f"  - {code} PE：{pe:.2f} PB：{pb:.2f} ROE：{roe:.2f}%")
            parts.append("\n".join(lines))

        if fundamentals:
            lines = ["基本面分析："]
            for f in fundamentals:
                code = f.get("code", "")
                rating = f.get("rating", "")
                summary = f.get("summary", "")
                lines.append(f"  - {code} 评级：{rating} | {summary}")
            parts.append("\n".join(lines))

        if allocation:
            lines = ["资产配置建议："]
            weights = allocation.get("weights", {})
            for code, weight in weights.items():
                lines.append(f"  - {code}：{float(weight)*100:.1f}%")
            if allocation.get("expected_return") is not None:
                lines.append(f"  预期年化收益率：{float(allocation['expected_return'])*100:.2f}%")
            if allocation.get("expected_volatility") is not None:
                lines.append(f"  预期年化波动率：{float(allocation['expected_volatility'])*100:.2f}%")
            if allocation.get("sharpe_ratio") is not None:
                lines.append(f"  夏普比率：{float(allocation['sharpe_ratio']):.3f}")
            parts.append("\n".join(lines))

        # 其他非标准事实
        extra = {}
        for key, value in facts_to_show.items():
            if key.endswith("__source"):
                continue
            if key in {"user_profile", "allocation_result"}:
                continue
            if (key.startswith("stock_quote_") or key.startswith("stock_history_")
                    or key.startswith("financial_indicator_") or key.startswith("stock_basic_info_")
                    or key.startswith("fundamental_analysis_")):
                continue
            extra[key] = value

        if extra:
            for key, value in extra.items():
                parts.append(f"{key}: {value}")

        return "\n".join(parts) if parts else ""

    def format_state_summary(self) -> str:
        """生成当前共享内存的状态摘要。"""
        with self._lock:
            parts = []
            parts.append(f"事实数: {len([k for k in self.facts if not k.endswith('__source')])}")
            parts.append(f"假设数: {len(self.hypotheses)}")
            parts.append(f"冲突数: {len([c for c in self.contradictions.values() if not c.get('resolved')])}")
            parts.append(f"消息数: {len(self.messages)}")
            return " | ".join(parts)

    # ── 会话管理 ─────────────────────────────────────────────

    def reset(self) -> None:
        """重置当前会话的工作内存。"""
        with self._lock:
            self.facts.clear()
            self.hypotheses.clear()
            self.contradictions.clear()
            self.messages.clear()
            self.stats.clear()

    def snapshot(self) -> Dict[str, Any]:
        """生成当前状态快照（用于调试和日志）。"""
        with self._lock:
            return {
                "facts_count": len([k for k in self.facts if not k.endswith("__source")]),
                "hypotheses_count": len(self.hypotheses),
                "pending_contradictions": sum(
                    1 for c in self.contradictions.values() if not c.get("resolved")
                ),
                "message_count": len(self.messages),
                "stats": dict(self.stats),
                "facts_sample": {
                    k: v for k, v in list(self.facts.items())[:5]
                    if not k.endswith("__source")
                },
            }
