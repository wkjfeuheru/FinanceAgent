"""主题特征刷新只处理有效成员。"""

from datetime import datetime, timedelta, timezone

from finance_agent.research.refresh import ThemeFeatureRefresher
from finance_agent.research.theme_models import ThemeLead
from finance_agent.research.theme_repository import InMemoryThemeRepository


def test_refresh_skips_pending_and_expired_members():
    repo = InMemoryThemeRepository()
    active = repo.ingest_lead(ThemeLead(theme_id="ai", stock_code="600519", industry="A", source_name="f", source_class="official", source_uri="https://e/a", evidence_excerpt="a", evidence_hash="a", discovered_at=datetime.now(timezone.utc)))
    repo.review_lead(active.id, reviewer_id="admin", decision="approve", expires_at=datetime.now(timezone.utc) + timedelta(days=1), note="ok")
    repo.ingest_lead(ThemeLead(theme_id="ai", stock_code="600520", industry="A", source_name="f", source_class="official", source_uri="https://e/b", evidence_excerpt="b", evidence_hash="b", discovered_at=datetime.now(timezone.utc)))

    summary = ThemeFeatureRefresher(repo, lambda code: {"code": code}).run("ai", datetime.now(timezone.utc))

    assert summary.refreshed_codes == ["600519"]
    assert summary.skipped_pending == ["600520"]
