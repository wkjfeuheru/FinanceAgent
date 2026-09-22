"""主题候选池审核仓储。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

from finance_agent.research.theme_models import ThemeLead, ThemeMembership


class ThemeRepository(Protocol):
    def ingest_lead(self, lead: ThemeLead) -> ThemeLead: ...
    def pending_leads(self, theme_id: str) -> list[ThemeLead]: ...
    def active_members(self, theme_id: str, as_of: datetime) -> list[ThemeMembership]: ...
    def expired_member_codes(self, theme_id: str, as_of: datetime) -> list[str]: ...


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

    def expired_member_codes(self, theme_id: str, as_of: datetime) -> list[str]:
        self.expire_stale_records(as_of)
        return [
            member.stock_code for member in self._members.values()
            if member.theme_id == theme_id and member.status == "expired"
        ]


class PostgresThemeRepository:
    """PostgreSQL 主题仓储；所有状态变更均由数据库事务完成。"""

    def __init__(self, connection_factory):
        self._connection_factory = connection_factory

    def ingest_lead(self, lead: ThemeLead) -> ThemeLead:
        """幂等写入证据和 pending 成员，绝不在导入时激活。"""
        connection = self._connection_factory()
        try:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO finance.theme_memberships
                    (membership_id, lead_id, theme_id, stock_code, industry, status, evidence_expires_at, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, 'pending', %s, %s, %s)
                    ON CONFLICT (lead_id) DO NOTHING
                    """,
                    (lead.id, lead.id, lead.theme_id, lead.stock_code, lead.industry,
                     lead.discovered_at + timedelta(days=30), lead.discovered_at, lead.discovered_at),
                )
                cursor.execute(
                    """
                    INSERT INTO finance.theme_evidence
                    (evidence_id, lead_id, source_name, source_class, source_uri, evidence_excerpt, evidence_hash, discovered_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (lead_id, evidence_hash) DO NOTHING
                    """,
                    (str(uuid4()), lead.id, lead.source_name, lead.source_class, lead.source_uri,
                     lead.evidence_excerpt, lead.evidence_hash, lead.discovered_at),
                )
            finally:
                cursor.close()
            connection.commit()
            return lead
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _rows(self, statement: str, params: tuple) -> list[tuple]:
        connection = self._connection_factory()
        try:
            cursor = connection.cursor()
            try:
                cursor.execute(statement, params)
                return list(cursor.fetchall())
            finally:
                cursor.close()
        finally:
            connection.close()

    def pending_leads(self, theme_id: str) -> list[ThemeLead]:
        rows = self._rows(
            """SELECT m.lead_id, m.theme_id, m.stock_code, m.industry, e.source_name,
                      e.source_class, e.source_uri, e.evidence_excerpt, e.evidence_hash, e.discovered_at
               FROM finance.theme_memberships m JOIN finance.theme_evidence e ON e.lead_id = m.lead_id
               WHERE m.theme_id = %s AND m.status = 'pending' ORDER BY e.discovered_at""", (theme_id,),
        )
        return [ThemeLead(id=str(row[0]), theme_id=row[1], stock_code=row[2], industry=row[3],
                          source_name=row[4], source_class=row[5], source_uri=row[6],
                          evidence_excerpt=row[7], evidence_hash=row[8], discovered_at=row[9]) for row in rows]

    def active_members(self, theme_id: str, as_of: datetime) -> list[ThemeMembership]:
        self.expire_stale_records(as_of)
        rows = self._rows(
            """SELECT membership_id, lead_id, theme_id, stock_code, industry, status,
                      evidence_expires_at, created_at, activated_at
               FROM finance.theme_memberships WHERE theme_id = %s AND status = 'active'
               AND evidence_expires_at > %s ORDER BY stock_code""", (theme_id, as_of),
        )
        return [ThemeMembership(id=str(row[0]), lead_id=str(row[1]), theme_id=row[2], stock_code=row[3],
                                industry=row[4], status=row[5], evidence_expires_at=row[6],
                                created_at=row[7], activated_at=row[8]) for row in rows]

    def expired_member_codes(self, theme_id: str, as_of: datetime) -> list[str]:
        self.expire_stale_records(as_of)
        rows = self._rows(
            """SELECT stock_code FROM finance.theme_memberships
               WHERE theme_id = %s AND status = 'expired' ORDER BY stock_code""",
            (theme_id,),
        )
        return [str(row[0]) for row in rows]

    def review_lead(self, lead_id: str, *, reviewer_id: str, decision: Literal["approve", "reject"],
                    expires_at: datetime, note: str) -> ThemeMembership:
        connection = self._connection_factory()
        try:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """UPDATE finance.theme_memberships SET status = %s, evidence_expires_at = %s,
                        activated_at = CASE WHEN %s = 'approve' THEN now() ELSE NULL END, updated_at = now()
                        WHERE lead_id = %s AND status = 'pending'
                        RETURNING membership_id, lead_id, theme_id, stock_code, industry, status,
                                  evidence_expires_at, created_at, activated_at""",
                    ('active' if decision == 'approve' else 'rejected', expires_at, decision, lead_id),
                )
                row = cursor.fetchone()
                if row is None:
                    raise ValueError("只有待审核线索可以被审核")
                cursor.execute("INSERT INTO finance.theme_reviews (review_id, lead_id, reviewer_id, decision, note) VALUES (%s, %s, %s, %s, %s)",
                               (str(uuid4()), lead_id, reviewer_id, decision, note))
            finally:
                cursor.close()
            connection.commit()
            return ThemeMembership(id=str(row[0]), lead_id=str(row[1]), theme_id=row[2], stock_code=row[3], industry=row[4],
                                   status=row[5], evidence_expires_at=row[6], created_at=row[7], activated_at=row[8])
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def expire_stale_records(self, as_of: datetime) -> int:
        pending_deadline = as_of - timedelta(days=30)
        connection = self._connection_factory()
        try:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """UPDATE finance.theme_memberships SET status = 'expired', updated_at = %s
                       WHERE (status = 'pending' AND created_at < %s)
                          OR (status = 'active' AND evidence_expires_at <= %s)""",
                    (as_of, pending_deadline, as_of),
                )
                count = int(getattr(cursor, "rowcount", 0) or 0)
            finally:
                cursor.close()
            connection.commit()
            return count
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


class PostgresFeatureSnapshotRepository:
    """PostgreSQL 特征快照读写仓储，供日终刷新和回测共享。"""

    def __init__(self, connection_factory):
        self._connection_factory = connection_factory

    def save_feature_snapshot(
        self, *, theme_id: str, stock_code: str, industry: str, rule_version: str,
        as_of: datetime, payload: dict[str, Any],
    ) -> None:
        import json

        connection = self._connection_factory()
        try:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """INSERT INTO finance.research_feature_snapshots
                       (snapshot_id, theme_id, stock_code, rule_version, as_of, payload)
                       VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                       ON CONFLICT (theme_id, stock_code, rule_version, as_of)
                       DO UPDATE SET payload = EXCLUDED.payload""",
                    (str(uuid4()), theme_id, stock_code, rule_version, as_of,
                     json.dumps({"industry": industry, **payload}, ensure_ascii=False)),
                )
            finally:
                cursor.close()
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def snapshots_before(self, theme_id: str, rule_version: str, as_of: datetime):
        from finance_agent.research.backtest import FeatureSnapshot

        connection = self._connection_factory()
        try:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """SELECT stock_code, as_of, payload FROM finance.research_feature_snapshots
                       WHERE theme_id = %s AND rule_version = %s AND as_of <= %s
                       ORDER BY stock_code, as_of""",
                    (theme_id, rule_version, as_of),
                )
                rows = list(cursor.fetchall())
            finally:
                cursor.close()
        finally:
            connection.close()
        return [
            FeatureSnapshot(
                theme_id=theme_id,
                stock_code=str(row[0]),
                industry=str((row[2] or {}).get("industry", "")),
                rule_version=rule_version,
                as_of=row[1],
                payload=dict(row[2] or {}),
            )
            for row in rows
        ]
