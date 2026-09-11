"""Provider 驱动的主题线索发现服务。"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Literal, Protocol

from finance_agent.research.theme_models import ThemeLead
from finance_agent.research.theme_repository import ThemeRepository


class ThemeDiscoveryProvider(Protocol):
    def discover(self, theme_id: str) -> Iterable[ThemeLead | dict[str, Any]]: ...


class ConfiguredThemeDiscoveryProvider:
    """将外部分类服务的原始记录规范成仅可审核的主题线索。"""

    def __init__(
        self,
        *,
        endpoint: str,
        source_name: str,
        source_class: Literal["official", "licensed_classification", "public_lead"],
        fetch_records: Callable[[str, str], Iterable[dict[str, Any]]] | None = None,
        api_token: str = "",
        timeout_seconds: float = 15.0,
    ):
        self._endpoint = endpoint.strip()
        self._source_name = source_name.strip()
        self._source_class = source_class
        self._fetch_records = fetch_records
        self._api_token = api_token.strip()
        self._timeout_seconds = timeout_seconds
        if not self._endpoint or not self._source_name:
            raise ValueError("主题发现服务必须配置 endpoint 和 source_name")

    def _http_records(self, theme_id: str) -> Iterable[dict[str, Any]]:
        import requests

        headers = {"Authorization": f"Bearer {self._api_token}"} if self._api_token else {}
        response = requests.get(
            self._endpoint,
            params={"theme_id": theme_id},
            headers=headers,
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            payload = payload.get("leads", payload.get("items", []))
        if not isinstance(payload, list):
            raise ValueError("主题发现服务必须返回线索列表")
        return [item for item in payload if isinstance(item, dict)]

    def discover(self, theme_id: str) -> Iterable[dict[str, Any]]:
        records = (
            self._fetch_records(self._endpoint, theme_id)
            if self._fetch_records is not None
            else self._http_records(theme_id)
        )
        normalized: list[dict[str, Any]] = []
        for raw in records:
            if not isinstance(raw, dict):
                normalized.append({"theme_id": theme_id})
                continue
            record = dict(raw)
            source_uri = str(record.get("source_uri", "")).strip()
            excerpt = str(record.get("evidence_excerpt", "")).strip()
            record.update({
                "theme_id": record.get("theme_id") or theme_id,
                "source_name": self._source_name,
                "source_class": self._source_class,
                "evidence_hash": record.get("evidence_hash") or ThemeLead.evidence_digest(source_uri, excerpt),
                "discovered_at": record.get("discovered_at") or datetime.now(timezone.utc),
            })
            normalized.append(record)
        return normalized


def configured_theme_discovery_provider() -> ConfiguredThemeDiscoveryProvider:
    """从环境配置创建生产发现 Provider，凭据不进入数据库或响应。"""
    from finance_agent.config import (
        THEME_DISCOVERY_API_TOKEN,
        THEME_DISCOVERY_ENDPOINT,
        THEME_DISCOVERY_SOURCE_CLASS,
        THEME_DISCOVERY_SOURCE_NAME,
        THEME_DISCOVERY_TIMEOUT,
    )

    return ConfiguredThemeDiscoveryProvider(
        endpoint=THEME_DISCOVERY_ENDPOINT,
        source_name=THEME_DISCOVERY_SOURCE_NAME,
        source_class=THEME_DISCOVERY_SOURCE_CLASS,
        api_token=THEME_DISCOVERY_API_TOKEN,
        timeout_seconds=THEME_DISCOVERY_TIMEOUT,
    )


@dataclass(frozen=True)
class DiscoverySummary:
    theme_id: str
    inserted_pending: int = 0
    duplicates: int = 0
    rejected: int = 0
    status: str = "completed"
    error_type: str = ""
    error_message: str = ""


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
        try:
            records = self._provider.discover(theme_id)
            iterator = iter(records)
        except Exception as exc:
            return DiscoverySummary(
                theme_id=theme_id, status="failed",
                error_type=type(exc).__name__, error_message=str(exc),
            )
        try:
            records_list = list(iterator)
        except Exception as exc:
            return DiscoverySummary(
                theme_id=theme_id, status="failed",
                error_type=type(exc).__name__, error_message=str(exc),
            )
        for raw in records_list:
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


def sync_configured_theme_leads(theme_id: str) -> DiscoverySummary:
    """将配置的外部 Provider 线索写入 PostgreSQL 待审核区。"""
    from finance_agent.config import get_postgres_connection_factory
    from finance_agent.data.postgres_repository import PostgresRuntimeRepository
    from finance_agent.research.theme_repository import PostgresThemeRepository

    connection_factory = get_postgres_connection_factory()
    PostgresRuntimeRepository(connection_factory).setup_schema()
    return ThemeDiscoveryService(
        configured_theme_discovery_provider(),
        PostgresThemeRepository(connection_factory),
    ).sync(theme_id)


def main(argv: list[str] | None = None) -> int:
    """执行冷启动主题发现并输出待审核线索汇总。"""
    parser = argparse.ArgumentParser(description="从配置的 Provider 同步主题待审核线索")
    parser.add_argument("--theme-id", action="append", dest="theme_ids", default=[])
    args = parser.parse_args(argv)
    from finance_agent.config import THEME_DISCOVERY_IDS

    theme_ids = list(dict.fromkeys([*args.theme_ids, *THEME_DISCOVERY_IDS]))
    if not theme_ids:
        print(json.dumps({"status": "no_theme_ids_configured", "themes": []}, ensure_ascii=False))
        return 0
    summaries = [sync_configured_theme_leads(theme_id) for theme_id in theme_ids]
    print(json.dumps(
        {"status": "completed", "themes": [summary.__dict__ for summary in summaries]},
        ensure_ascii=False,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
