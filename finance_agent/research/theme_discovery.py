"""Provider 驱动的主题线索发现服务。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Protocol

from finance_agent.research.theme_models import ThemeLead
from finance_agent.research.theme_repository import ThemeRepository


class ThemeDiscoveryProvider(Protocol):
    def discover(self, theme_id: str) -> Iterable[ThemeLead | dict[str, Any]]: ...


@dataclass(frozen=True)
class DiscoverySummary:
    theme_id: str
    inserted_pending: int = 0
    duplicates: int = 0
    rejected: int = 0


class ThemeDiscoveryService:
    """发现服务只写入待审核区，不赋予成员生效、评分或行动结论。"""

    def __init__(self, provider: ThemeDiscoveryProvider, repository: ThemeRepository):
        self._provider = provider
        self._repository = repository

    def sync(self, theme_id: str) -> DiscoverySummary:
        inserted = duplicates = rejected = 0
        existing = {
            (lead.stock_code, lead.source_name, lead.evidence_hash)
            for lead in self._repository.pending_leads(theme_id)
        }
        for raw in self._provider.discover(theme_id):
            try:
                lead = raw if isinstance(raw, ThemeLead) else ThemeLead.model_validate(raw)
                if lead.theme_id != theme_id:
                    raise ValueError("主题不一致")
            except (TypeError, ValueError):
                rejected += 1
                continue
            key = (lead.stock_code, lead.source_name, lead.evidence_hash)
            if key in existing:
                duplicates += 1
                continue
            self._repository.ingest_lead(lead)
            existing.add(key)
            inserted += 1
        return DiscoverySummary(theme_id, inserted, duplicates, rejected)
