"""外部主题发现只能创建待审核线索。"""

from datetime import datetime, timezone

from finance_agent.research.theme_discovery import ConfiguredThemeDiscoveryProvider, ThemeDiscoveryService
from finance_agent.research.theme_models import ThemeLead
from finance_agent.research.theme_repository import InMemoryThemeRepository


class FixtureProvider:
    def discover(self, theme_id: str):
        return [ThemeLead(
            theme_id=theme_id,
            stock_code="600519",
            industry="算力",
            source_name="fixture",
            source_class="public_lead",
            source_uri="https://example.com/lead",
            evidence_excerpt="公开线索，等待人工核验",
            evidence_hash="discovery-hash",
            discovered_at=datetime.now(timezone.utc),
        )]


def test_external_discovery_creates_pending_only():
    repository = InMemoryThemeRepository()
    summary = ThemeDiscoveryService(FixtureProvider(), repository).sync("ai_compute")

    assert summary.inserted_pending == 1
    assert repository.active_members("ai_compute", datetime.now(timezone.utc)) == []


def test_same_evidence_hash_is_idempotent():
    repository = InMemoryThemeRepository()
    service = ThemeDiscoveryService(FixtureProvider(), repository)
    service.sync("ai_compute")
    service.sync("ai_compute")

    assert len(repository.pending_leads("ai_compute")) == 1


def test_missing_source_uri_is_rejected_before_storage():
    class BadProvider:
        def discover(self, theme_id: str):
            return [{"theme_id": theme_id, "stock_code": "600519"}]

    summary = ThemeDiscoveryService(BadProvider(), InMemoryThemeRepository()).sync("bad_theme")

    assert summary.rejected == 1


def test_configured_provider_normalizes_external_records_as_pending_leads():
    """防止外部冷启动数据绕过审核服务直接成为有效候选。"""
    provider = ConfiguredThemeDiscoveryProvider(
        endpoint="https://provider.example/themes",
        source_name="授权分类服务",
        source_class="licensed_classification",
        fetch_records=lambda endpoint, theme_id: [{
            "stock_code": "600519", "industry": "算力", "source_uri": "https://provider.example/evidence/1",
            "evidence_excerpt": "分类服务发现的关联证据",
        }],
    )
    repository = InMemoryThemeRepository()

    summary = ThemeDiscoveryService(provider, repository).sync("ai_compute")

    assert summary.inserted_pending == 1
    assert repository.active_members("ai_compute", datetime.now(timezone.utc)) == []
    lead = repository.pending_leads("ai_compute")[0]
    assert lead.source_class == "licensed_classification"
    assert lead.evidence_hash == ThemeLead.evidence_digest(lead.source_uri, lead.evidence_excerpt)
