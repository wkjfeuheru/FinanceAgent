"""主题特征刷新只处理有效成员。"""

from datetime import datetime, timedelta, timezone

from finance_agent.research.refresh import ThemeFeatureRefresher
from finance_agent.research.theme_models import ThemeLead
from finance_agent.research.theme_repository import InMemoryThemeRepository


class RecordingFeatureStore:
    def __init__(self):
        self.snapshots = []

    def save_feature_snapshot(self, **snapshot):
        self.snapshots.append(snapshot)


def test_refresh_skips_pending_and_expired_members():
    repo = InMemoryThemeRepository()
    active = repo.ingest_lead(ThemeLead(theme_id="ai", stock_code="600519", industry="A", source_name="f", source_class="official", source_uri="https://e/a", evidence_excerpt="a", evidence_hash="a", discovered_at=datetime.now(timezone.utc)))
    repo.review_lead(active.id, reviewer_id="admin", decision="approve", expires_at=datetime.now(timezone.utc) + timedelta(days=1), note="ok")
    repo.ingest_lead(ThemeLead(theme_id="ai", stock_code="600520", industry="A", source_name="f", source_class="official", source_uri="https://e/b", evidence_excerpt="b", evidence_hash="b", discovered_at=datetime.now(timezone.utc)))
    expired = repo.ingest_lead(ThemeLead(theme_id="ai", stock_code="600521", industry="B", source_name="f", source_class="official", source_uri="https://e/c", evidence_excerpt="c", evidence_hash="c", discovered_at=datetime.now(timezone.utc)))
    repo.review_lead(expired.id, reviewer_id="admin", decision="approve", expires_at=datetime.now(timezone.utc) - timedelta(days=1), note="已过期")

    summary = ThemeFeatureRefresher(repo, lambda code: {"code": code}).run("ai", datetime.now(timezone.utc))

    assert summary.refreshed_codes == ["600519"]
    assert summary.skipped_pending == ["600520"]
    assert summary.skipped_expired == ["600521"]


def test_refresh_persists_only_successful_active_member_features():
    repo = InMemoryThemeRepository()
    lead = repo.ingest_lead(ThemeLead(theme_id="ai", stock_code="600519", industry="A", source_name="f", source_class="official", source_uri="https://e/a", evidence_excerpt="a", evidence_hash="a", discovered_at=datetime.now(timezone.utc)))
    repo.review_lead(lead.id, reviewer_id="admin", decision="approve", expires_at=datetime.now(timezone.utc) + timedelta(days=1), note="ok")
    store = RecordingFeatureStore()

    summary = ThemeFeatureRefresher(
        repo, lambda code: {"total_score": 80, "code": code}, feature_store=store,
    ).run("ai", datetime.now(timezone.utc))

    assert summary.failures == {}
    assert len(store.snapshots) == 1
    assert store.snapshots[0]["theme_id"] == "ai"
    assert store.snapshots[0]["stock_code"] == "600519"
    assert store.snapshots[0]["industry"] == "A"
    assert store.snapshots[0]["rule_version"] == "research_rules/v1.2"
    assert store.snapshots[0]["payload"] == {"total_score": 80, "code": "600519"}
