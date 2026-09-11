"""主题候选池审核仓储。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal, Protocol

from finance_agent.research.theme_models import ThemeLead, ThemeMembership


class ThemeRepository(Protocol):
    def ingest_lead(self, lead: ThemeLead) -> ThemeLead: ...
    def pending_leads(self, theme_id: str) -> list[ThemeLead]: ...
    def active_members(self, theme_id: str, as_of: datetime) -> list[ThemeMembership]: ...


class InMemoryThemeRepository:
    """可复用的内存实现，供业务测试和本地发现流程使用。"""

    def __init__(self) -> None:
        self._leads: dict[str, ThemeLead] = {}
        self._lead_by_evidence: dict[tuple[str, str, str, str], str] = {}
        self._members: dict[str, ThemeMembership] = {}

    def ingest_lead(self, lead: ThemeLead) -> ThemeLead:
        key = (lead.theme_id, lead.stock_code, lead.source_name, lead.evidence_hash)
        previous = self._lead_by_evidence.get(key)
        if previous:
            return self._leads[previous]
        self._leads[lead.id] = lead
        self._lead_by_evidence[key] = lead.id
        self._members[lead.id] = ThemeMembership(
            id=lead.id,
            lead_id=lead.id,
            theme_id=lead.theme_id,
            stock_code=lead.stock_code,
            industry=lead.industry,
            status="pending",
            evidence_expires_at=lead.discovered_at + timedelta(days=30),
            created_at=lead.discovered_at,
        )
        return lead

    def pending_leads(self, theme_id: str) -> list[ThemeLead]:
        return [
            lead for lead_id, lead in self._leads.items()
            if lead.theme_id == theme_id and self._members[lead_id].status == "pending"
        ]

    def review_lead(
        self, lead_id: str, *, reviewer_id: str, decision: Literal["approve", "reject"],
        expires_at: datetime, note: str,
    ) -> ThemeMembership:
        del reviewer_id, note
        member = self._members.get(lead_id)
        if member is None:
            raise KeyError("主题线索不存在")
        if member.status != "pending":
            raise ValueError("只有待审核线索可以被审核")
        now = datetime.now(timezone.utc)
        updated = member.model_copy(update={
            "status": "active" if decision == "approve" else "rejected",
            "evidence_expires_at": expires_at,
            "activated_at": now if decision == "approve" else None,
        })
        self._members[lead_id] = updated
        return updated

    def expire_stale_records(self, as_of: datetime) -> int:
        count = 0
        for lead_id, member in list(self._members.items()):
            expired_pending = member.status == "pending" and member.created_at < as_of - timedelta(days=30)
            expired_active = member.status == "active" and member.evidence_expires_at <= as_of
            if expired_pending or expired_active:
                self._members[lead_id] = member.model_copy(update={"status": "expired"})
                count += 1
        return count

    def active_members(self, theme_id: str, as_of: datetime) -> list[ThemeMembership]:
        self.expire_stale_records(as_of)
        return [
            member for member in self._members.values()
            if member.theme_id == theme_id and member.status == "active" and member.evidence_expires_at > as_of
        ]
