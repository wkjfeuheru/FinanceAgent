"""主题审核接口的授权测试。"""

import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from finance_agent.api import routes
from finance_agent.research.theme_models import ThemeLead
from finance_agent.research.theme_registry import InMemoryThemeRegistry, ThemeEntry
from finance_agent.research.theme_repository import InMemoryThemeRepository


class Request:
    def __init__(self):
        self.headers = {"Authorization": "Bearer token"}


def test_non_admin_cannot_list_pending_leads(monkeypatch):
    monkeypatch.setattr(routes, "_require_customer_id", lambda request: "USER1")
    monkeypatch.setattr(routes, "ADMIN_CUSTOMER_IDS", {"ADMIN1"})

    with pytest.raises(HTTPException) as exc:
        asyncio.run(routes.list_theme_leads(Request(), "ai_compute"))
    assert exc.value.status_code == 403


def test_admin_can_approve_pending_lead(monkeypatch):
    repo = InMemoryThemeRepository()
    lead = repo.ingest_lead(ThemeLead(
        theme_id="ai_compute", stock_code="600519", industry="算力",
        source_name="fixture", source_class="official", source_uri="https://e/1",
        evidence_excerpt="公告", evidence_hash="h", discovered_at=datetime.now(timezone.utc),
    ))
    monkeypatch.setattr(routes, "_require_customer_id", lambda request: "ADMIN1")
    monkeypatch.setattr(routes, "ADMIN_CUSTOMER_IDS", {"ADMIN1"})
    monkeypatch.setattr(routes, "get_theme_repository", lambda: repo)
    payload = routes.ThemeLeadReviewRequest(
        decision="approve", evidence_expires_at="2027-09-10T00:00:00Z", note="公告核验",
    )

    response = asyncio.run(routes.review_theme_lead(lead.id, payload, Request()))

    assert response["status"] == "active"


def _admin(monkeypatch, registry=None):
    monkeypatch.setattr(routes, "_require_customer_id", lambda request: "ADMIN1")
    monkeypatch.setattr(routes, "ADMIN_CUSTOMER_IDS", {"ADMIN1"})
    if registry is not None:
        monkeypatch.setattr(routes, "get_theme_registry", lambda: registry)


def test_non_admin_cannot_manage_theme_registry(monkeypatch):
    monkeypatch.setattr(routes, "_require_customer_id", lambda request: "USER1")
    monkeypatch.setattr(routes, "ADMIN_CUSTOMER_IDS", {"ADMIN1"})

    with pytest.raises(HTTPException) as exc:
        asyncio.run(routes.list_registered_themes(Request()))
    assert exc.value.status_code == 403


def test_admin_upserts_and_lists_theme_registry(monkeypatch):
    registry = InMemoryThemeRegistry()
    _admin(monkeypatch, registry)
    payload = routes.ThemeRegistryUpsertRequest(
        theme_id="new_energy", display_name="新能源",
        aliases=["新能源车", "锂电", "新能源"], active=True,
    )

    created = asyncio.run(routes.upsert_registered_theme(payload, Request()))
    listed = asyncio.run(routes.list_registered_themes(Request()))

    assert created.theme_id == "new_energy"
    assert created.aliases == ["新能源车", "锂电", "新能源"]
    assert [entry.theme_id for entry in listed] == ["new_energy"]
    assert registry.resolve("锂电") == "new_energy"


def test_upsert_rejects_reserved_theme_id(monkeypatch):
    _admin(monkeypatch, InMemoryThemeRegistry())
    payload = routes.ThemeRegistryUpsertRequest(
        theme_id="market_insight", display_name="保留", aliases=[],
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(routes.upsert_registered_theme(payload, Request()))
    assert exc.value.status_code == 400


def test_deactivate_soft_deletes_and_stops_resolving(monkeypatch):
    registry = InMemoryThemeRegistry([
        ThemeEntry(theme_id="ai_compute", display_name="AI算力", aliases=["算力"]),
    ])
    _admin(monkeypatch, registry)

    result = asyncio.run(routes.deactivate_registered_theme(Request(), "ai_compute"))

    assert result == {"theme_id": "ai_compute", "active": False}
    assert registry.resolve("算力") is None
    assert registry.list_themes() == []


def test_deactivate_unknown_theme_is_404(monkeypatch):
    _admin(monkeypatch, InMemoryThemeRegistry())

    with pytest.raises(HTTPException) as exc:
        asyncio.run(routes.deactivate_registered_theme(Request(), "nope"))
    assert exc.value.status_code == 404
