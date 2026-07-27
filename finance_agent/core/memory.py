from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
import redis
from finance_agent.config import REDIS_MEMORY_TTL_SECONDS, REDIS_URL


@dataclass
class UserProfileCard:
    """金融投顾用户画像卡 —— 用户级别的长期档案，跨对话共享。"""
    customer_id: str
    risk_preference: str = ""          # 风险偏好：R1低风险 ~ R5高风险
    budget_amount: float = 0.0          # 预算金额（元）
    stock_codes: list[str] = field(default_factory=list)  # 用户主动关注的A股代码（跨对话持久）
    holding_period: str = ""           # 持有时间（如 "3个月"、"1年"）
    investment_goal: str = ""          # 投资目标（如 "稳健增值"、"高收益"）
    confirmed_facts: dict[str, Any] = field(default_factory=dict)
    updated_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UserProfileCard":
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        if "investment_horizon" in data and "holding_period" not in data:
            data["holding_period"] = data.pop("investment_horizon")
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)


# ── Profile checkpoint helper ───────────────────────────────────

def _profile_thread_id(customer_id: str) -> str:
    return f"profile:{customer_id.upper()}"


# ── Redis 层 ─────────────────────────────────────────────────

class RedisMemoryStore:
    """对话级别的 Redis 记忆存储。

    每个 conversation_id 独立拥有：
    - 滑动窗口消息（最近 N 条）
    - 近期摘要
    - 用户画像缓存（从 SQLite 同步过来的快照）

    对话之间完全隔离。
    """

    def __init__(
        self,
        redis_url: str = REDIS_URL,
        ttl_seconds: int = REDIS_MEMORY_TTL_SECONDS,
    ):
        self.redis_url = redis_url
        self.ttl_seconds = ttl_seconds
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

    # ── 消息历史（按 conversation 隔离，保留兼容旧接口）─────────

    def append_message(
        self,
        customer_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Deprecated: 旧接口，写入 customer-scoped 消息列表。"""
        payload = {
            "role": role,
            "content": content,
            "metadata": metadata or {},
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        try:
            client = self._get_client()
            key = self._key(customer_id)
            client.rpush(key, json.dumps(payload, ensure_ascii=False))
            client.expire(key, self.ttl_seconds)
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
        return [json.loads(value) for value in values]

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

    # ── 对话级窗口消息 ─────────────────────────────────────────

    def append_window_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        window_size: int = 5,
    ) -> bool:
        """向指定对话的滑动窗口追加一条消息。"""
        payload = {
            "role": role,
            "content": content,
            "metadata": metadata or {},
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        try:
            client = self._get_client()
            key = self._window_key(conversation_id)
            client.rpush(key, json.dumps(payload, ensure_ascii=False))
            client.ltrim(key, -abs(window_size), -1)
            client.expire(key, self.ttl_seconds)
            self._last_error = ""
            return True
        except redis.RedisError as exc:
            self._last_error = str(exc)
            return False

    def get_window_messages(self, conversation_id: str, window_size: int = 5) -> list[dict[str, Any]]:
        try:
            values = self._get_client().lrange(
                self._window_key(conversation_id), -abs(window_size), -1,
            )
            self._last_error = ""
        except redis.RedisError as exc:
            self._last_error = str(exc)
            return []
        return [json.loads(value) for value in values]

    def set_window_messages(
        self,
        conversation_id: str,
        messages: list[dict[str, Any]],
        window_size: int = 5,
    ) -> bool:
        """用给定消息列表替换指定对话的滑动窗口。"""
        try:
            client = self._get_client()
            key = self._window_key(conversation_id)
            client.delete(key)
            for msg in messages[-window_size:]:
                payload = {
                    "role": msg.get("role", ""),
                    "content": msg.get("content", ""),
                    "metadata": msg.get("metadata", {}),
                    "timestamp": msg.get("timestamp", datetime.now().isoformat(timespec="seconds")),
                }
                client.rpush(key, json.dumps(payload, ensure_ascii=False))
            if messages[-window_size:]:
                client.expire(key, self.ttl_seconds)
            self._last_error = ""
            return True
        except redis.RedisError as exc:
            self._last_error = str(exc)
            return False

    # ── 对话级摘要 ─────────────────────────────────────────────

    def get_summary(self, conversation_id: str) -> str:
        try:
            value = self._get_client().get(self._summary_key(conversation_id))
            self._last_error = ""
            return value or ""
        except redis.RedisError as exc:
            self._last_error = str(exc)
            return ""

    def set_summary(self, conversation_id: str, summary: str) -> bool:
        try:
            self._get_client().set(
                self._summary_key(conversation_id),
                summary,
                ex=self.ttl_seconds,
            )
            self._last_error = ""
            return True
        except redis.RedisError as exc:
            self._last_error = str(exc)
            return False

    # ── Redis key 命名 ──────────────────────────────────────────

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
        """Deprecated: 旧版 customer-scoped 消息列表键。"""
        return f"finance_cs:{customer_id.upper()}:messages"

    def _profile_key(self, customer_id: str) -> str:
        return f"finance_cs:{customer_id.upper()}:profile"

    def _summary_key(self, conversation_id: str) -> str:
        """对话级摘要键。"""
        return f"finance_cs:conv:{conversation_id}:summary"

    def _window_key(self, conversation_id: str) -> str:
        """对话级滑动窗口键。"""
        return f"finance_cs:conv:{conversation_id}:window"

    def clear_conversation(self, conversation_id: str) -> bool:
        """清除指定对话的记忆数据（窗口 + 摘要）。"""
        try:
            self._get_client().delete(
                self._window_key(conversation_id),
                self._summary_key(conversation_id),
            )
            self._last_error = ""
            return True
        except redis.RedisError as exc:
            self._last_error = str(exc)
            return False


# ── 记忆上下文 ─────────────────────────────────────────────────

class AgentMemoryContext:
    """按对话隔离的 Agent 记忆上下文。

    三层记忆：
    1. 用户档案卡 —— checkpoint 持久化，跨对话共享（风险偏好、预算等）
    2. 对话摘要 —— 当前对话的压缩历史（Redis，按 conversation_id）
    3. 滑动窗口 —— 当前对话的最近 N 条消息（Redis，按 conversation_id）

    对话 A 的窗口和摘要不会泄露到对话 B。
    """

    def __init__(
        self,
        store: RedisMemoryStore | None = None,
        checkpointer: Any = None,
        window_size: int = 6,
        summary_size: int = 10,
        max_context_chars: int = 6000,
    ):
        self.store = store or RedisMemoryStore()
        self.checkpointer = checkpointer
        self.window_size = window_size
        self.summary_size = summary_size
        self.max_context_chars = max_context_chars

    # ── 对话级 load/save ────────────────────────────────────────

    def load_context(
        self,
        customer_id: str,
        conversation_id: str,
        fallback_messages: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """加载当前对话的完整上下文。"""
        profile = self.get_profile(customer_id)
        profile_text = self.format_profile(profile)
        recent_summary = self.store.get_summary(conversation_id)
        sliding_window = self.store.get_window_messages(conversation_id, self.window_size)
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
        conversation_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """向当前对话的滑动窗口追加一条消息。"""
        return self.store.append_window_message(
            conversation_id, role, content, metadata, self.window_size,
        )

    def update_recent_summary(
        self,
        conversation_id: str,
        messages: list[dict[str, Any]],
    ) -> bool:
        """确定性地滚动更新当前对话摘要，不额外调用大模型。

        调用方只需传入本轮新增消息。已有摘要会与本轮摘要合并，并按
        ``max_context_chars`` 的一半限制长度；滑动窗口仍独立保存最近 N 条
        原始消息。这样下一轮可同时注入较早摘要和最近原文。
        """
        existing = self.store.get_summary(conversation_id).strip()
        current = self.build_rule_summary(messages[-self.summary_size:]).strip()
        if existing and current and not existing.endswith(current):
            summary = f"{existing}\n{current}"
        else:
            summary = current or existing

        summary_limit = max(1000, self.max_context_chars // 2)
        summary = self._fit_text(summary, summary_limit)
        return self.store.set_summary(conversation_id, summary)

    # ── 用户档案（checkpoint 持久化，跨对话共享）────────────────

    def get_profile(self, customer_id: str) -> UserProfileCard:
        """从 checkpoint 加载用户画像。"""
        if self.checkpointer is None:
            return UserProfileCard(customer_id=customer_id.upper())

        try:
            config = {"configurable": {"thread_id": _profile_thread_id(customer_id)}}
            ckpt = self.checkpointer.get(config)
            if ckpt and ckpt.get("channel_values"):
                data = ckpt["channel_values"].get("user_profile")
                if data:
                    data.setdefault("customer_id", customer_id.upper())
                    return UserProfileCard.from_dict(data)
        except Exception:
            pass
        return UserProfileCard(customer_id=customer_id.upper())

    def save_profile(self, profile: UserProfileCard) -> bool:
        """将用户画像写入 checkpoint。"""
        if self.checkpointer is None:
            return False
        profile.updated_at = datetime.now().isoformat(timespec="seconds")
        thread_id = _profile_thread_id(profile.customer_id)
        profile_dict = asdict(profile)
        now = profile.updated_at
        ckpt_id = now  # use timestamp as stable checkpoint id
        try:
            self.checkpointer.put(
                {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": "",
                    }
                },
                {
                    "v": 1,
                    "id": ckpt_id,
                    "ts": now,
                    "channel_values": {
                        "user_profile": profile_dict,
                        "updated_at": now,
                    },
                    "channel_versions": {
                        "user_profile": ckpt_id,
                        "updated_at": ckpt_id,
                    },
                    "versions_seen": {},
                    "updated_channels": None,
                },
                {
                    "source": "user_profile",
                    "customer_id": profile.customer_id.upper(),
                    "step": 0,
                },
                {"user_profile": ckpt_id, "updated_at": ckpt_id},
            )
            return True
        except Exception:
            return False

    def update_profile_from_result(
        self,
        customer_id: str,
        user_message: str,
        result: dict[str, Any],
    ) -> bool:
        """从用户消息和本轮结果中抽取投资参数，更新用户长期画像。

        注意：只有用户在消息中明确输入的股票代码才进入长期画像。
        行业/主题搜索返回的推荐候选不进入。
        """
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

        # 持有时间抽取
        horizon_match = re.search(r"(\d+)\s*(天|周|个月|月|年)", user_message)
        if horizon_match:
            horizon = "".join(horizon_match.groups())
            if profile.holding_period != horizon:
                profile.holding_period = horizon
                changed = True

        # 预算金额抽取
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
                    if value >= 100:
                        profile.budget_amount = value
                        changed = True
                        break
                except ValueError:
                    pass

        # 使用槽位 Agent 的本轮抽取结果更新投资目标。该字段不能只依赖长期画像，
        # 否则“我的投资目标是……”在快速选股流程中不会同步到右侧画像。
        result_profile = result.get("user_profile", {}) or {}
        investment_goal = (
            str(result_profile.get("investment_goal", "") or "").strip()
            if isinstance(result_profile, dict)
            else ""
        )
        if investment_goal and profile.investment_goal != investment_goal:
            profile.investment_goal = investment_goal
            changed = True

        # 只持久化用户在当前消息中明确输入的股票代码
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

    # ── 格式化工具 ───────────────────────────────────────────────

    def compose_context(self, profile_text: str, recent_summary: str, sliding_window_text: str) -> str:
        sections = []
        if profile_text:
            sections.append(f"[长期记忆 - 用户档案卡]\n{profile_text}")
        remaining = self.max_context_chars - sum(len(section) for section in sections)

        if recent_summary and remaining > 0:
            summary = self._fit_text(recent_summary, max(0, remaining))
            if summary:
                sections.append(f"[对话摘要 - 当前对话]\n{summary}")
        remaining = self.max_context_chars - sum(len(section) for section in sections)

        if sliding_window_text and remaining > 0:
            window = self._fit_window_text(sliding_window_text, remaining)
            if window:
                sections.append(f"[滑动窗口 - 当前对话最近 {self.window_size} 条]\n{window}")

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

    def build_intent_context(self, messages: list[dict[str, Any]]) -> str:
        """为意图模型压缩最近三轮对话，不包含长期画像或累计摘要。"""
        lines: list[str] = []
        for item in list(messages or [])[-6:]:
            role = "用户" if item.get("role") == "user" else "客服"
            content = str(item.get("content", "")).strip().replace("\n", " ")
            if len(content) > 180:
                content = content[:177] + "..."
            if content:
                lines.append(f"{role}: {content}")
        summary = "\n".join(lines)
        return self._fit_text(summary, 1500)

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
