from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
import redis
from finance_agent.config import REDIS_MEMORY_TTL_SECONDS, REDIS_URL
from finance_agent.orchestrator.database import get_database


@dataclass
class UserProfileCard:
    """金融投顾用户画像卡 —— 用户级别的长期档案，跨对话共享。"""
    customer_id: str
    risk_preference: str = ""          # 风险偏好：R1低风险 ~ R5高风险
    budget_amount: float = 0.0          # 预算金额（元）
    stock_codes: list[str] = field(default_factory=list)  # 用户主动关注的A股代码（跨对话持久）
    holding_period: str = ""           # 持有时间（如 "3个月"、"1年"）
    investment_goal: str = ""           # 投资目标（如 "稳健增值"、"高收益"）
    confirmed_facts: dict[str, Any] = field(default_factory=dict)
    updated_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UserProfileCard":
        """从业务存储快照恢复画像，并忽略历史未知字段。"""
        payload = dict(data)
        if "investment_horizon" in payload and "holding_period" not in payload:
            payload["holding_period"] = payload.pop("investment_horizon")
        known_fields = {field.name for field in cls.__dataclass_fields__.values()}
        return cls(**{key: value for key, value in payload.items() if key in known_fields})


@dataclass(frozen=True)
class ProfileFactCandidate:
    """本轮解析出的画像候选；未确认候选不得直接覆盖长期画像。"""

    field: str
    value: Any
    source: str = "user_message"
    confirmed: bool = False

# ── Redis 层 ─────────────────────────────────────────────────

class RedisMemoryStore:
    """对话级别的 Redis 记忆存储。

    每个 conversation_id 独立拥有：
    - 滑动窗口消息（最近 N 条）
    - 近期摘要
    - 用户画像缓存（从 PostgreSQL 同步的快照）

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

    # ── 消息历史 ─────────────────────────────────────────────────
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

    def _summary_key(self, conversation_id: str) -> str:
        """对话级摘要键。"""
        return f"finance_cs:conv:{conversation_id}:summary"

    def _window_key(self, conversation_id: str) -> str:
        """对话级滑动窗口键。"""
        return f"finance_cs:conv:{conversation_id}:window"

    def set_short_cache(self, namespace: str, key: str, value: Any, ttl_seconds: int | None = None) -> bool:
        """写入带 TTL 的临时事实缓存，不承担业务事实持久化。"""
        try:
            self._get_client().set(
                self._cache_key(namespace, key),
                json.dumps(value, ensure_ascii=False),
                ex=ttl_seconds or self.ttl_seconds,
            )
            self._last_error = ""
            return True
        except redis.RedisError as exc:
            self._last_error = str(exc)
            return False

    def get_short_cache(self, namespace: str, key: str) -> Any | None:
        """读取临时事实缓存；Redis 故障或缓存缺失均返回 None。"""
        try:
            value = self._get_client().get(self._cache_key(namespace, key))
            self._last_error = ""
            return json.loads(value) if value else None
        except (redis.RedisError, json.JSONDecodeError) as exc:
            self._last_error = str(exc)
            return None

    def _cache_key(self, namespace: str, key: str) -> str:
        return f"finance_cs:cache:{namespace}:{key}"

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
        max_context_tokens: int | None = None,
        profile_loader: Any = None,
        messages_loader: Any = None,
    ):
        self.store = store or RedisMemoryStore()
        self.checkpointer = checkpointer
        self.window_size = window_size
        self.summary_size = summary_size
        self.max_context_chars = max_context_chars
        self.max_context_tokens = max_context_tokens or max(1, max_context_chars // 4)
        self.profile_loader = profile_loader
        self.messages_loader = messages_loader

    # ── 对话级 load/save ────────────────────────────────────────

    def load_context(
        self,
        customer_id: str,
        conversation_id: str,
        fallback_messages: list[dict[str, Any]] | None = None,
        task_facts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """加载当前对话上下文，并按任务事实优先级执行预算裁剪。"""
        profile = self.get_profile(customer_id)
        profile_text = self.format_profile(profile)
        availability_check = getattr(self.store, "is_available", None)
        redis_available = availability_check() if availability_check else True
        recent_summary = self.store.get_summary(conversation_id) if redis_available else ""
        sliding_window = (
            self.store.get_window_messages(conversation_id, self.window_size)
            if redis_available else []
        )
        if not redis_available and self.messages_loader:
            sliding_window = self.messages_loader(conversation_id, self.window_size)
        if not sliding_window and fallback_messages:
            sliding_window = fallback_messages[-self.window_size:]
        sliding_window_text = self.format_messages(sliding_window)
        task_facts_text = self.format_task_facts(task_facts or [])
        context_text = self.compose_context(
            profile_text, recent_summary, sliding_window_text, task_facts_text,
        )
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

    # ── 用户档案（finance_agent.db 持久化，跨对话共享）────────────────

    def get_profile(self, customer_id: str) -> UserProfileCard:
        """从业务事实源加载用户画像；缓存层不作为长期事实源。"""
        try:
            if self.profile_loader:
                data = self.profile_loader(customer_id)
            else:
                db = get_database()
                data = db.get_profile(customer_id)
            if data:
                if isinstance(data, UserProfileCard):
                    return data
                data.setdefault("customer_id", customer_id.upper())
                return UserProfileCard.from_dict(data)
        except Exception:
            pass
        return UserProfileCard(customer_id=customer_id.upper())

    def save_profile(self, profile: UserProfileCard) -> bool:
        """将用户画像写入 finance_agent.db 的 user_profiles 表。"""
        profile.updated_at = datetime.now().isoformat(timespec="seconds")
        try:
            db = get_database()
            db.save_profile(asdict(profile))
            return True
        except Exception:
            return False

    def extract_profile_candidates(
        self,
        user_message: str,
    ) -> list[ProfileFactCandidate]:
        """仅从用户原话提取画像候选，不执行长期记忆写入。"""
        candidates: list[ProfileFactCandidate] = []
        message = user_message.lower()
        risk_map = [
            ("R5 高风险", ["r5", "高风险", "进取", "激进"]),
            ("R4 中高风险", ["r4", "中高风险", "积极"]),
            ("R3 中风险", ["r3", "中风险", "平衡"]),
            ("R2 中低风险", ["r2", "中低风险", "稳健"]),
            ("R1 低风险", ["r1", "低风险", "保守"]),
        ]
        explicit_risk = re.search(
            r"(?:我的)?(?:风险偏好|风险承受能力|投资风格)(?:是|为|偏向|：|:)?\s*([^，。；;\n]+)",
            user_message,
        )
        if explicit_risk:
            risk_text = explicit_risk.group(1).lower()
            for value, keywords in risk_map:
                if any(keyword in risk_text for keyword in keywords):
                    candidates.append(ProfileFactCandidate("risk_preference", value, confirmed=True))
                    break
        else:
            for value, keywords in risk_map:
                if any(keyword in message for keyword in keywords):
                    candidates.append(ProfileFactCandidate("risk_preference", value))
                    break

        horizon_match = re.search(r"(\d+)\s*(天|周|个月|月|年)", user_message)
        if horizon_match:
            candidates.append(ProfileFactCandidate(
                "holding_period", "".join(horizon_match.groups()), confirmed=True,
            ))

        amount_match = re.search(r"(\d+(?:\.\d+)?)\s*万", user_message)
        if amount_match:
            candidates.append(ProfileFactCandidate(
                "budget_amount", float(amount_match.group(1)) * 10000, confirmed=True,
            ))
        else:
            amount_match = re.search(r"(\d+(?:\.\d+)?)\s*元", user_message)
            if amount_match and float(amount_match.group(1)) >= 100:
                candidates.append(ProfileFactCandidate(
                    "budget_amount", float(amount_match.group(1)), confirmed=True,
                ))

        goal_match = re.search(
            r"(?:我的)?投资目标(?:是|为|：|:)\s*([^，。；;\n]+)",
            user_message,
        )
        if goal_match:
            candidates.append(ProfileFactCandidate(
                "investment_goal", goal_match.group(1).strip(), confirmed=True,
            ))

        stock_codes = re.findall(
            r"(?<!\d)(60\d{4}|00\d{4}|30\d{4}|68\d{4}|8\d{5}|4\d{5})(?!\d)",
            user_message,
        )
        for code in stock_codes:
            candidates.append(ProfileFactCandidate("stock_code", code, confirmed=True))
        return candidates

    def apply_confirmed_facts(
        self,
        customer_id: str,
        candidates: list[ProfileFactCandidate],
    ) -> bool:
        """只将已明确确认的候选写入长期画像，专家结果不会绕过此门控。"""
        profile = self.get_profile(customer_id)
        changed = False
        for candidate in candidates:
            if not candidate.confirmed or candidate.source != "user_message":
                continue
            if candidate.field == "stock_code":
                if candidate.value not in profile.stock_codes:
                    profile.stock_codes.append(str(candidate.value))
                    changed = True
                continue
            if candidate.field not in {
                "risk_preference", "budget_amount", "holding_period", "investment_goal",
            }:
                continue
            if getattr(profile, candidate.field) != candidate.value:
                setattr(profile, candidate.field, candidate.value)
                profile.confirmed_facts[candidate.field] = candidate.value
                changed = True
        return self.save_profile(profile) if changed else True

    def update_profile_from_result(
        self,
        customer_id: str,
        user_message: str,
        result: dict[str, Any] | None = None,
    ) -> bool:
        """兼容旧调用方：仅依据用户原话写入，忽略模型和专家推测。"""
        del result
        return self.apply_confirmed_facts(
            customer_id,
            self.extract_profile_candidates(user_message),
        )

    # ── 格式化工具 ───────────────────────────────────────────────

    def compose_context(
        self,
        profile_text: str,
        recent_summary: str,
        sliding_window_text: str,
        task_facts_text: str = "",
    ) -> str:
        """按任务事实、消息、摘要、画像优先级组装受限工作记忆。"""
        sections: list[str] = []
        remaining = self._context_limit_chars()
        for label, text in (
            ("[本轮任务事实]", task_facts_text),
            ("[滑动窗口 - 当前对话最近消息]", sliding_window_text),
            ("[对话摘要 - 当前对话]", recent_summary),
            ("[长期记忆 - 用户档案卡]", profile_text),
        ):
            if not text or remaining <= 0:
                continue
            content_limit = max(0, remaining - len(label) - 1)
            fitted = (
                self._fit_window_text(text, content_limit)
                if "滑动窗口" in label
                else self._fit_text(text, content_limit)
            )
            if fitted:
                section = f"{label}\n{fitted}"
                sections.append(section)
                remaining -= len(section) + 2
        return "\n\n".join(sections)

    def format_task_facts(self, facts: list[dict[str, Any]]) -> str:
        """格式化数据准备阶段提供的任务相关事实。"""
        lines: list[str] = []
        for fact in facts:
            fact_id = str(fact.get("fact_id", ""))
            payload = fact.get("payload", {})
            if fact_id and payload:
                lines.append(f"{fact_id}: {json.dumps(payload, ensure_ascii=False)}")
        return "\n".join(lines)

    def _context_limit_chars(self) -> int:
        """将 token 预算转换为 Demo 阶段的保守字符预算。"""
        return min(self.max_context_chars, self.max_context_tokens * 4)

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
        if limit <= 0:
            return ""
        if len(text) <= limit:
            return text
        lines = text.splitlines()
        kept: list[str] = []
        total = 0
        for line in reversed(lines):
            available = limit - total
            if available <= 0:
                break
            # 保留最新消息；单条消息过长时保留其尾部而不是整条丢弃。
            fitted = line[-available:]
            kept.append(fitted)
            total += len(fitted) + 1
        return "\n".join(reversed(kept))[-limit:]
