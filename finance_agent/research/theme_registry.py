"""主题注册表：把用户自由文本映射为已治理的 ``theme_id``。

解析器只依赖本模块的 ``ThemeRegistry`` 协议；生产接线注入 PostgreSQL 读路径，
无数据库时回退内置静态别名表，保证解析器保持纯函数可测。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

# 内置主题别名：仅覆盖仓库已实现的主题，供无数据库环境与单元测试使用。
_BUILTIN_ALIASES: dict[str, tuple[str, ...]] = {
    "ai_compute": ("人工智能", "AI", "ai", "算力", "AI算力", "人工智能主题"),
}


@dataclass(frozen=True)
class ThemeEntry:
    """一条主题注册记录。"""

    theme_id: str
    display_name: str
    aliases: list[str] = field(default_factory=list)
    active: bool = True

    def names(self) -> list[str]:
        return [self.display_name, *self.aliases]


class ThemeRegistry(Protocol):
    """主题名 → theme_id 的只读解析协议。"""

    def resolve(self, name: str) -> str | None: ...

    def list_themes(self) -> list[ThemeEntry]: ...


class InMemoryThemeRegistry:
    """内存实现，供测试与本地调用。"""

    def __init__(self, entries: list[ThemeEntry] | None = None) -> None:
        self._entries = list(entries or [])

    def resolve(self, name: str) -> str | None:
        needle = (name or "").strip()
        if not needle:
            return None
        lowered = needle.lower()
        for entry in self._entries:
            if not entry.active:
                continue
            if entry.theme_id == needle:
                return entry.theme_id
            if any(token.lower() == lowered for token in entry.names()):
                return entry.theme_id
        return None

    def list_themes(self) -> list[ThemeEntry]:
        return [entry for entry in self._entries if entry.active]

    def upsert(self, entry: ThemeEntry) -> ThemeEntry:
        """新增或替换同 theme_id 的记录。"""
        self._entries = [item for item in self._entries if item.theme_id != entry.theme_id]
        self._entries.append(entry)
        return entry

    def deactivate(self, theme_id: str) -> bool:
        """软删除：置 ``active=false``。返回是否命中。"""
        hit = any(entry.theme_id == theme_id for entry in self._entries)
        self._entries = [
            ThemeEntry(
                theme_id=entry.theme_id, display_name=entry.display_name,
                aliases=list(entry.aliases),
                active=False if entry.theme_id == theme_id else entry.active,
            )
            for entry in self._entries
        ]
        return hit


class StaticThemeRegistry(InMemoryThemeRegistry):
    """由内置别名表构造的静态注册表。"""

    @classmethod
    def builtin(cls) -> "StaticThemeRegistry":
        return cls([
            ThemeEntry(theme_id=theme_id, display_name=theme_id, aliases=list(aliases))
            for theme_id, aliases in _BUILTIN_ALIASES.items()
        ])


class PostgresThemeRegistry:
    """PostgreSQL 读路径；读失败时显式抛错，由调用方决定回退。"""

    def __init__(self, connection_factory) -> None:
        self._connection_factory = connection_factory

    def _rows(self) -> list[Any]:
        connection = self._connection_factory()
        try:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "SELECT theme_id, display_name, aliases FROM finance.themes WHERE active = true",
                )
                return list(cursor.fetchall())
            finally:
                cursor.close()
        finally:
            connection.close()

    def list_themes(self) -> list[ThemeEntry]:
        entries: list[ThemeEntry] = []
        for row in self._rows():
            raw_aliases = row[2]
            if isinstance(raw_aliases, str):
                import json

                try:
                    raw_aliases = json.loads(raw_aliases)
                except (TypeError, ValueError):
                    raw_aliases = []
            aliases = [str(item) for item in (raw_aliases or []) if str(item).strip()]
            entries.append(ThemeEntry(
                theme_id=str(row[0]), display_name=str(row[1] or row[0]), aliases=aliases,
            ))
        return entries

    def resolve(self, name: str) -> str | None:
        return InMemoryThemeRegistry(self.list_themes()).resolve(name)

    def upsert(self, entry: ThemeEntry) -> ThemeEntry:
        """新增或更新主题（含别名），供 admin 管理接口使用。"""
        import json

        connection = self._connection_factory()
        try:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """INSERT INTO finance.themes (theme_id, display_name, aliases, active, updated_at)
                       VALUES (%s, %s, %s::jsonb, %s, now())
                       ON CONFLICT (theme_id) DO UPDATE SET
                         display_name = EXCLUDED.display_name,
                         aliases = EXCLUDED.aliases,
                         active = EXCLUDED.active,
                         updated_at = now()""",
                    (entry.theme_id, entry.display_name,
                     json.dumps(entry.aliases, ensure_ascii=False), entry.active),
                )
            finally:
                cursor.close()
            connection.commit()
            return entry
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def deactivate(self, theme_id: str) -> bool:
        """软删除：置 ``active=false``，保留历史映射与审计。返回是否命中一行。"""
        connection = self._connection_factory()
        try:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "UPDATE finance.themes SET active = false, updated_at = now() WHERE theme_id = %s",
                    (theme_id,),
                )
                affected = int(getattr(cursor, "rowcount", 0) or 0)
            finally:
                cursor.close()
            connection.commit()
            return affected > 0
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


class FallbackThemeRegistry:
    """优先使用 primary（如 PostgreSQL 读路径），失败时回退 fallback（内置别名）。"""

    def __init__(self, primary: ThemeRegistry, fallback: ThemeRegistry) -> None:
        self._primary = primary
        self._fallback = fallback

    def resolve(self, name: str) -> str | None:
        try:
            resolved = self._primary.resolve(name)
        except Exception:  # noqa: BLE001 - 读路径失败不得阻断主流程
            return self._fallback.resolve(name)
        return resolved or self._fallback.resolve(name)

    def list_themes(self) -> list[ThemeEntry]:
        try:
            entries = self._primary.list_themes()
        except Exception:  # noqa: BLE001
            return self._fallback.list_themes()
        return entries or self._fallback.list_themes()


_STATIC_REGISTRY = StaticThemeRegistry.builtin()


def default_theme_registry() -> ThemeRegistry:
    """返回默认注册表；生产环境由调用方注入 PostgreSQL 读路径。"""
    return _STATIC_REGISTRY


def production_theme_registry() -> ThemeRegistry:
    """生产注册表：PostgreSQL 读路径优先，不可用时回退内置别名。"""
    try:
        from finance_agent.config import get_postgres_connection_factory

        return FallbackThemeRegistry(
            PostgresThemeRegistry(get_postgres_connection_factory()), _STATIC_REGISTRY,
        )
    except Exception:  # noqa: BLE001
        return _STATIC_REGISTRY


__all__ = [
    "FallbackThemeRegistry",
    "InMemoryThemeRegistry",
    "PostgresThemeRegistry",
    "StaticThemeRegistry",
    "ThemeEntry",
    "ThemeRegistry",
    "default_theme_registry",
    "production_theme_registry",
]
