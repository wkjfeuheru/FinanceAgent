"""Redis-backed conversational memory adapter."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import redis

from finance_agent.infrastructure.settings import REDIS_MEMORY_TTL_SECONDS, REDIS_URL

logger = logging.getLogger(__name__)


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
            # 健康探测失败是后续降级的根因，必须留下日志（否则 Redis 宕机期间
            # 每轮静默降级无人知晓）。
            logger.warning("memory_store_unavailable error=%s", exc)
            return False

    # ── 对话级窗口消息 ─────────────────────────────────────────

    def append_window_message(
        self,
        customer_id: str,
        conversation_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        window_size: int = 5,
    ) -> bool:
        """向指定客户指定对话的滑动窗口追加一条消息。"""
        payload = {
            "role": role,
            "content": content,
            "metadata": metadata or {},
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        try:
            client = self._get_client()
            key = self._window_key(customer_id, conversation_id)
            client.rpush(key, json.dumps(payload, ensure_ascii=False))
            client.ltrim(key, -abs(window_size), -1)
            client.expire(key, self.ttl_seconds)
            self._last_error = ""
            return True
        except redis.RedisError as exc:
            self._last_error = str(exc)
            logger.warning(
                "append_window_message_failed customer_id=%s conversation_id=%s error=%s",
                customer_id, conversation_id, exc,
            )
            return False

    def get_window_messages(
        self, customer_id: str, conversation_id: str, window_size: int = 5,
    ) -> list[dict[str, Any]]:
        try:
            values = self._get_client().lrange(
                self._window_key(customer_id, conversation_id), -abs(window_size), -1,
            )
            self._last_error = ""
        except redis.RedisError as exc:
            self._last_error = str(exc)
            logger.warning(
                "get_window_messages_failed customer_id=%s conversation_id=%s error=%s",
                customer_id, conversation_id, exc,
            )
            return []
        return [json.loads(value) for value in values]

    # ── 对话级摘要 ─────────────────────────────────────────────

    def get_summary(self, customer_id: str, conversation_id: str) -> str:
        try:
            value = self._get_client().get(self._summary_key(customer_id, conversation_id))
            self._last_error = ""
            return value or ""
        except redis.RedisError as exc:
            self._last_error = str(exc)
            logger.warning(
                "get_summary_failed customer_id=%s conversation_id=%s error=%s",
                customer_id, conversation_id, exc,
            )
            return ""

    def set_summary(self, customer_id: str, conversation_id: str, summary: str) -> bool:
        try:
            self._get_client().set(
                self._summary_key(customer_id, conversation_id),
                summary,
                ex=self.ttl_seconds,
            )
            self._last_error = ""
            return True
        except redis.RedisError as exc:
            self._last_error = str(exc)
            logger.warning(
                "set_summary_failed customer_id=%s conversation_id=%s error=%s",
                customer_id, conversation_id, exc,
            )
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

    def _summary_key(self, customer_id: str, conversation_id: str) -> str:
        """客户 + 对话级摘要键；按客户隔离，避免仅凭 conversation_id 越权读写。"""
        return f"finance_cs:conv:{str(customer_id).upper()}:{conversation_id}:summary"

    def _window_key(self, customer_id: str, conversation_id: str) -> str:
        """客户 + 对话级滑动窗口键。"""
        return f"finance_cs:conv:{str(customer_id).upper()}:{conversation_id}:window"

    def clear_conversation(self, customer_id: str, conversation_id: str) -> bool:
        """清除指定客户指定对话的记忆数据（窗口 + 摘要）。"""
        try:
            self._get_client().delete(
                self._window_key(customer_id, conversation_id),
                self._summary_key(customer_id, conversation_id),
            )
            self._last_error = ""
            return True
        except redis.RedisError as exc:
            self._last_error = str(exc)
            logger.warning(
                "clear_conversation_failed customer_id=%s conversation_id=%s error=%s",
                customer_id, conversation_id, exc,
            )
            return False


__all__ = ["RedisMemoryStore"]
