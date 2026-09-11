"""主题有效成员的日终特征刷新。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from finance_agent.research.theme_repository import ThemeRepository


@dataclass(frozen=True)
class RefreshSummary:
    theme_id: str
    refreshed_codes: list[str] = field(default_factory=list)
    skipped_pending: list[str] = field(default_factory=list)
    failures: dict[str, str] = field(default_factory=dict)


class ThemeFeatureRefresher:
    """刷新器不为失败成员写入占位评分。持久化由调用方仓储适配器处理。"""

    def __init__(self, themes: ThemeRepository, fetch_feature: Callable[[str], dict[str, Any]]):
        self._themes = themes
        self._fetch_feature = fetch_feature

    def run(self, theme_id: str, as_of: datetime | None = None) -> RefreshSummary:
        now = as_of or datetime.now(timezone.utc)
        active = self._themes.active_members(theme_id, now)
        active_codes = {member.stock_code for member in active}
        pending = [lead.stock_code for lead in self._themes.pending_leads(theme_id) if lead.stock_code not in active_codes]
        refreshed: list[str] = []
        failures: dict[str, str] = {}
        for member in active:
            try:
                self._fetch_feature(member.stock_code)
                refreshed.append(member.stock_code)
            except Exception as exc:
                failures[member.stock_code] = str(exc)
        return RefreshSummary(theme_id, refreshed, pending, failures)
