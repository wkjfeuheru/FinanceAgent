"""主题审核接口的授权测试。"""

import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from finance_agent.api import routes
from finance_agent.research.theme_models import ThemeLead
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
