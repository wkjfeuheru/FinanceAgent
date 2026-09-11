"""主题候选池的审核隔离与生命周期测试。"""

from datetime import datetime, timedelta, timezone

from finance_agent.research.theme_models import ThemeLead
from finance_agent.research.theme_repository import InMemoryThemeRepository


def _lead() -> ThemeLead:
    return ThemeLead(
        theme_id="ai_compute",
        stock_code="600519",
        industry="算力",
        source_name="fixture",
        source_class="official",
        source_uri="https://example.com/disclosure",
        evidence_excerpt="与主题相关的正式披露",
        evidence_hash="fixture-hash",
        discovered_at=datetime.now(timezone.utc),
    )


def test_pending_lead_is_not_active():
    repository = InMemoryThemeRepository()
    repository.ingest_lead(_lead())

    assert repository.active_members("ai_compute", as_of=datetime.now(timezone.utc)) == []
    assert len(repository.pending_leads("ai_compute")) == 1


def test_only_review_activates_pending_lead():
    repository = InMemoryThemeRepository()
    lead = repository.ingest_lead(_lead())

    member = repository.review_lead(
        lead.id,
        reviewer_id="ADMIN1",
        decision="approve",
        expires_at=datetime.now(timezone.utc) + timedelta(days=365),
        note="公告核验",
    )

    assert member.status == "active"


def test_expired_member_is_excluded():
    repository = InMemoryThemeRepository()
    lead = repository.ingest_lead(_lead())
    repository.review_lead(
        lead.id,
        reviewer_id="ADMIN1",
        decision="approve",
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        note="已过期",
    )

    repository.expire_stale_records(datetime.now(timezone.utc))

    assert repository.active_members("ai_compute", datetime.now(timezone.utc)) == []
