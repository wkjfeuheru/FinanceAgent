from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
import redis
from finance_agent.config import REDIS_URL
from finance_agent.core.database import SQLiteStore, get_database


@dataclass
class UserProfileCard:
    """金融投顾用户画像卡。"""
    customer_id: str
    risk_preference: str = ""          # 风险偏好：R1低风险 ~ R5高风险
    budget_amount: float = 0.0          # 预算金额（元）
    stock_codes: list[str] = field(default_factory=list)  # 关注的A股代码
    holding_period: str = ""           # 持有时间（如 "3个月"、"1年"）
    investment_goal: str = ""          # 投资目标（如 "稳健增值"、"高收益"）
    confirmed_facts: dict[str, Any] = field(default_factory=dict)
    updated_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UserProfileCard":
        """从字典创建画像卡，忽略未知字段以兼容旧数据。"""
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        # 兼容旧字段名 investment_horizon -> holding_period
        if "investment_horizon" in data and "holding_period" not in data:
            data["holding_period"] = data.pop("investment_horizon")
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)


class RedisMemoryStore:
    def __init__(self, redis_url: str = REDIS_URL):
        self.redis_url = redis_url
        self._client = None
        self._last_error = ""

    @property
    def last_error(self) -> str:
        return self._last_error

    def is_available(self) -> bool:
        try:
            self._get_client().ping()
            self._last_error = ""
            return True
        except redis.RedisError as exc:
            self._last_error = str(exc)
            return False

    def append_message(
        self,
        customer_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        payload = {
            "role": role,
            "content": content,
            "metadata": metadata or {},
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        try:
            self._get_client().rpush(self._key(customer_id), json.dumps(payload, ensure_ascii=False))
            self._last_error = ""
            return True
        except redis.RedisError as exc:
            self._last_error = str(exc)
            return False

    def get_messages(self, customer_id: str, limit: int = 50) -> list[dict[str, Any]]:
        try:
            values = self._get_client().lrange(self._key(customer_id), -limit, -1)
            self._last_error = ""
        except redis.RedisError as exc:
            self._last_error = str(exc)
            return []

        messages = []
        for value in values:
            messages.append(json.loads(value))
        return messages

    def clear_messages(self, customer_id: str) -> bool:
        try:
            self._get_client().delete(self._key(customer_id))
            self._get_client().delete(self._window_key(customer_id))
            self._get_client().delete(self._summary_key(customer_id))
            self._last_error = ""
            return True
        except redis.RedisError as exc:
            self._last_error = str(exc)
            return False

    def _get_client(self):
        if self._client is None:
            try:
                self._client = redis.Redis.from_url(
                    self.redis_url,
                    decode_responses=True,
                    protocol=2,
                )
            except TypeError:
                self._client = redis.Redis.from_url(self.redis_url, decode_responses=True)
        return self._client

    def _key(self, customer_id: str) -> str:
        return f"finance_cs:{customer_id.upper()}:messages"

    def _profile_key(self, customer_id: str) -> str:
        return f"finance_cs:{customer_id.upper()}:profile"

    def _summary_key(self, customer_id: str) -> str:
        return f"finance_cs:{customer_id.upper()}:recent_summary"

    def _window_key(self, customer_id: str) -> str:
        return f"finance_cs:{customer_id.upper()}:window"


class AgentMemoryContext:
    """三层 Agent memory：长期档案、近期摘要、滑动窗口。"""

    def __init__(
        self,
        store: RedisMemoryStore | None = None,
        window_size: int = 5,
        summary_size: int = 10,
        max_context_chars: int = 6000,
    ):
        self.store = store or RedisMemoryStore()
        self.database: SQLiteStore = get_database()
        self.window_size = window_size
        self.summary_size = summary_size
        self.max_context_chars = max_context_chars

    def load_context(
        self,
        customer_id: str,
        fallback_messages: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        profile = self.get_profile(customer_id)
        profile_text = self.format_profile(profile)
        recent_summary = self.get_recent_summary(customer_id)
        sliding_window = self.get_window_messages(customer_id)
        if not sliding_window and fallback_messages:
            sliding_window = fallback_messages[-self.window_size:]
        sliding_window_text = self.format_messages(sliding_window)
        context_text = self.compose_context(profile_text, recent_summary, sliding_window_text)
        return {
            "profile": asdict(profile),
            "profile_text": profile_text,
            "recent_summary": recent_summary,
            "sliding_window": sliding_window,
            "sliding_window_text": sliding_window_text,
            "context_text": context_text,
        }

    def append_window_message(
        self,
        customer_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        payload = {
            "role": role,
            "content": content,
            "metadata": metadata or {},
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        try:
            client = self.store._get_client()
            client.rpush(self.store._window_key(customer_id), json.dumps(payload, ensure_ascii=False))
            client.ltrim(self.store._window_key(customer_id), -self.window_size, -1)
            self.store._last_error = ""
            return True
        except redis.RedisError as exc:
            self.store._last_error = str(exc)
            return False

    def get_window_messages(self, customer_id: str) -> list[dict[str, Any]]:
        try:
            values = self.store._get_client().lrange(
                self.store._window_key(customer_id),
                -self.window_size,
                -1,
            )
            self.store._last_error = ""
        except redis.RedisError as exc:
            self.store._last_error = str(exc)
            return []
        return [json.loads(value) for value in values]

    def get_profile(self, customer_id: str) -> UserProfileCard:
        data = self.database.get_profile(customer_id)
        # One-time compatibility migration for profiles created before SQLite.
        if not data:
            try:
                raw = self.store._get_client().get(self.store._profile_key(customer_id))
                if raw:
                    data = json.loads(raw)
                    data.setdefault("customer_id", customer_id.upper())
                    self.database.save_profile(data)
                    self.store._get_client().delete(self.store._profile_key(customer_id))
            except (redis.RedisError, json.JSONDecodeError, sqlite3.Error, OSError, ValueError) as exc:
                self.store._last_error = str(exc)
        if not data:
            return UserProfileCard(customer_id=customer_id.upper())
        data.setdefault("customer_id", customer_id.upper())
        return UserProfileCard.from_dict(data)

    def save_profile(self, profile: UserProfileCard) -> bool:
        profile.updated_at = datetime.now().isoformat(timespec="seconds")
        try:
            self.database.save_profile(asdict(profile))
            return True
        except (OSError, ValueError, sqlite3.Error) as exc:
            self.store._last_error = str(exc)
            return False

    def get_recent_summary(self, customer_id: str) -> str:
        try:
            value = self.store._get_client().get(self.store._summary_key(customer_id))
            self.store._last_error = ""
            return value or ""
        except redis.RedisError as exc:
            self.store._last_error = str(exc)
            return ""

    def update_recent_summary(
        self,
        customer_id: str,
        messages: list[dict[str, Any]],
        summary_text: str = "",
    ) -> bool:
        recent = messages[-self.summary_size:]
        summary = summary_text.strip() or self.build_rule_summary(recent)
        try:
            self.store._get_client().set(self.store._summary_key(customer_id), summary)
            self.store._last_error = ""
            return True
        except redis.RedisError as exc:
            self.store._last_error = str(exc)
            return False

    def update_profile_from_result(
        self,
        customer_id: str,
        user_message: str,
        result: dict[str, Any],
    ) -> bool:
        """从用户消息中抽取投资参数更新画像。"""
        profile = self.get_profile(customer_id)
        changed = False
        message = user_message.lower()

        # 风险偏好识别 R1-R5
        risk_map = [
            ("R5 高风险", ["r5", "高风险", "进取", "激进"]),
            ("R4 中高风险", ["r4", "中高风险", "积极"]),
            ("R3 中风险", ["r3", "中风险", "平衡"]),
            ("R2 中低风险", ["r2", "中低风险", "稳健"]),
            ("R1 低风险", ["r1", "低风险", "保守"]),
        ]
        for value, keywords in risk_map:
            if any(keyword in message for keyword in keywords):
                if profile.risk_preference != value:
                    profile.risk_preference = value
                    changed = True
                break

        # 持有时间抽取（X天/周/月/年）
        horizon_match = re.search(r"(\d+)\s*(天|周|个月|月|年)", user_message)
        if horizon_match:
            horizon = "".join(horizon_match.groups())
            if profile.holding_period != horizon:
                profile.holding_period = horizon
                changed = True

        # 预算金额抽取（支持 万/元，转换为元）
        for amount_str in re.findall(r"(\d+(?:\.\d+)?)\s*万", user_message):
            try:
                value = float(amount_str) * 10000
                if profile.budget_amount != value:
                    profile.budget_amount = value
                    changed = True
                break
            except ValueError:
                pass
        if not profile.budget_amount:
            for amount_str in re.findall(r"(\d+(?:\.\d+)?)\s*元", user_message):
                try:
                    value = float(amount_str)
                    if value >= 100:  # 过滤小额
                        profile.budget_amount = value
                        changed = True
                        break
                except ValueError:
                    pass

        # 只持久化用户在当前消息中明确输入名称或代码的股票。
        # 行业/主题搜索返回的推荐候选只用于本轮分析，不进入关注列表。
        stock_codes = re.findall(
            r"(?<!\d)(60\d{4}|00\d{4}|30\d{4}|68\d{4}|8\d{5}|4\d{5})(?!\d)",
            user_message,
        )
        explicit_codes = result.get("explicit_user_stock_codes", [])
        if isinstance(explicit_codes, list):
            for code in explicit_codes:
                normalized = str(code).strip()
                if (
                    re.fullmatch(
                        r"(?:60\d{4}|00\d{4}|30\d{4}|68\d{4}|8\d{5}|4\d{5})",
                        normalized,
                    )
                    and normalized not in stock_codes
                ):
                    stock_codes.append(normalized)
        for code in stock_codes:
            if code not in profile.stock_codes:
                profile.stock_codes.append(code)
                changed = True

        if changed:
            return self.save_profile(profile)
        return True

    def compose_context(self, profile_text: str, recent_summary: str, sliding_window_text: str) -> str:
        sections = []
        if profile_text:
            sections.append(f"[长期记忆 - 用户档案卡]\n{profile_text}")
        remaining = self.max_context_chars - sum(len(section) for section in sections)

        if recent_summary and remaining > 0:
            summary = self._fit_text(recent_summary, max(0, remaining))
            if summary:
                sections.append(f"[近期对话摘要 - 最近10次]\n{summary}")
        remaining = self.max_context_chars - sum(len(section) for section in sections)

        if sliding_window_text and remaining > 0:
            window = self._fit_window_text(sliding_window_text, remaining)
            if window:
                sections.append(f"[滑动窗口 - 最近5条]\n{window}")

        return "\n\n".join(sections)

    def format_profile(self, profile: UserProfileCard) -> str:
        lines = []
        if profile.risk_preference:
            lines.append(f"风险偏好：{profile.risk_preference}")
        if profile.budget_amount:
            lines.append(f"预算金额：{profile.budget_amount:,.0f} 元")
        if profile.stock_codes:
            lines.append(f"关注股票：{', '.join(profile.stock_codes[-10:])}")
        if profile.holding_period:
            lines.append(f"持有时间：{profile.holding_period}")
        if profile.investment_goal:
            lines.append(f"投资目标：{profile.investment_goal}")
        for key, value in profile.confirmed_facts.items():
            lines.append(f"{key}：{value}")
        return "\n".join(lines)

    def format_messages(self, messages: list[dict[str, Any]]) -> str:
        lines = []
        for item in messages:
            role = "用户" if item.get("role") == "user" else "客服"
            content = str(item.get("content", "")).strip()
            if content:
                lines.append(f"{role}: {content}")
        return "\n".join(lines)

    def build_rule_summary(self, messages: list[dict[str, Any]]) -> str:
        if not messages:
            return ""
        facts = []
        for item in messages:
            role = "用户" if item.get("role") == "user" else "客服"
            content = str(item.get("content", "")).strip().replace("\n", " ")
            if not content:
                continue
            if len(content) > 180:
                content = content[:180] + "..."
            facts.append(f"{role}: {content}")
        return "\n".join(facts[-self.summary_size:])

    def _fit_text(self, text: str, limit: int) -> str:
        if limit <= 0:
            return ""
        return text if len(text) <= limit else text[-limit:]

    def _fit_window_text(self, text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        lines = text.splitlines()
        kept = []
        total = 0
        for line in reversed(lines):
            line_len = len(line) + 1
            if total + line_len > limit:
                break
            kept.append(line)
            total += line_len
        return "\n".join(reversed(kept))
