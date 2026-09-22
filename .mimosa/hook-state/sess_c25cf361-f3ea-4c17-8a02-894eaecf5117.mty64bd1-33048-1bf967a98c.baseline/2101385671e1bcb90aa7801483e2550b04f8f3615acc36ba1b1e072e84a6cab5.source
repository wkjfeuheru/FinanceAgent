"""行情与估值的本地落盘缓存（最小版本）。

只服务 K 线与估值两条路径，不做全量缓存框架。缓存键由调用方给出
``(provider, code, adjust, start, end)`` 这类元组，落盘为 JSON。

设计取舍：

- **失败不影响取数**：任何读写异常只记 warning。缓存是加速手段，不是正确性依赖。
- **``QUOTE_CACHE_TTL_SECONDS`` 为 0 表示关闭缓存**，便于排障与测试。
- 记录可能来自 ``DataFrame.to_dict``，因此含 numpy 标量，序列化时必须兼容，
  否则缓存会"静默永不生效"。
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from finance_agent import config

logger = logging.getLogger(__name__)


def _root() -> Path:
    """返回缓存根目录；每次读取配置，便于测试替换。"""
    return Path(config.QUOTE_CACHE_DIR)


def _entry_path(namespace: str, key: Iterable[Any]) -> Path:
    """按命名空间与键计算缓存文件路径。"""
    digest = hashlib.sha256("|".join(str(part) for part in key).encode("utf-8")).hexdigest()[:32]
    return _root() / namespace / f"{digest}.json"


def _json_default(value: Any) -> Any:
    """兼容 numpy 标量与日期类型，避免缓存因序列化失败而静默失效。"""
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return item()
        except Exception:  # numpy 之外的对象可能声明了不可调用的 item
            pass
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"无法序列化的缓存值：{type(value).__name__}")


def read(namespace: str, key: Iterable[Any], ttl_seconds: int | None = None) -> Any | None:
    """读取未过期的缓存记录；文件缺失、损坏或已过期时返回 ``None``。"""
    path = _entry_path(namespace, key)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    cached_at = payload.get("cached_at")
    if not isinstance(cached_at, (int, float)):
        return None
    ttl = config.QUOTE_CACHE_TTL_SECONDS if ttl_seconds is None else ttl_seconds
    if ttl <= 0 or time.time() - cached_at > ttl:
        return None
    return payload.get("records")


def write(namespace: str, key: Iterable[Any], records: Any, ttl_seconds: int | None = None) -> None:
    """写入缓存记录；任何失败只记 warning。"""
    path = _entry_path(namespace, key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"cached_at": time.time(), "ttl_seconds": ttl_seconds, "records": records},
                ensure_ascii=False,
                default=_json_default,
            ),
            encoding="utf-8",
        )
    except (OSError, TypeError, ValueError) as exc:
        logger.warning("写入行情缓存失败 %s: %s", path, exc)


def clear(namespace: str = "") -> None:
    """删除缓存文件；``namespace`` 为空时清空整个缓存根目录。"""
    root = _root() / namespace if namespace else _root()
    if not root.exists():
        return
    for path in sorted(root.rglob("*.json")):
        try:
            path.unlink()
        except OSError as exc:
            logger.warning("删除行情缓存失败 %s: %s", path, exc)


__all__ = ["clear", "read", "write"]
