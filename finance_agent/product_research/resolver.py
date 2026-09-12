"""产品代码和名称解析。"""

from __future__ import annotations

from typing import Any, Protocol

from .contracts import ProductReference


class ProductLookup(Protocol):
    def query_by_codes(self, codes: list[str]) -> list[dict[str, Any]]: ...
    def search_by_name(self, name: str) -> list[dict[str, Any]]: ...


def _product_code(item: dict[str, Any]) -> str:
    basic = item.get("basic_info") if isinstance(item.get("basic_info"), dict) else item
    return str((basic or {}).get("code", item.get("code", "")) or "").strip()


def _product_name(item: dict[str, Any]) -> str:
    basic = item.get("basic_info") if isinstance(item.get("basic_info"), dict) else item
    return str((basic or {}).get("name", item.get("name", "")) or "").strip()


class ProductReferenceResolver:
    """解析所有名称候选，禁止在歧义时静默选择第一条。"""

    def __init__(self, lookup: ProductLookup):
        self._lookup = lookup

    def resolve(
        self, codes: list[str], names: list[str],
    ) -> tuple[list[ProductReference], list[str]]:
        references: list[ProductReference] = []
        seen: set[str] = set()

        for raw_code in codes:
            code = str(raw_code).strip()
            if not code or code in seen:
                continue
            products = self._lookup.query_by_codes([code])
            if products:
                item = products[0]
                resolved_code = _product_code(item) or code
                references.append(ProductReference(code=resolved_code, name=_product_name(item)))
                seen.add(resolved_code)

        ambiguous: list[str] = []
        for raw_name in names:
            name = str(raw_name).strip()
            if not name:
                continue
            candidates = [item for item in self._lookup.search_by_name(name) if _product_code(item)]
            candidate_codes = list(dict.fromkeys(_product_code(item) for item in candidates))
            if len(candidate_codes) != 1:
                if len(candidate_codes) > 1:
                    ambiguous.append(name)
                continue
            code = candidate_codes[0]
            if code not in seen:
                item = next(item for item in candidates if _product_code(item) == code)
                references.append(ProductReference(code=code, name=_product_name(item) or name))
                seen.add(code)

        return references, ambiguous
