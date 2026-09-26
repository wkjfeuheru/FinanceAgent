"""产品代码和名称解析。"""

from __future__ import annotations

from typing import Any, Protocol

from finance_agent.shared import name_matching as name_match

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

    def _fuzzy_codes(self, name: str) -> list[str]:
        """LIKE 查不到时的简称/近似兜底；候选源不可用时返回空，不抛。

        命中多个产品时返回**全部**候选代码，让调用方按"≠1 即歧义"处理，而不是
        只回传唯一解析结果、把歧义悄悄吞掉。
        """
        lister = getattr(self._lookup, "list_active_names", None)
        if not callable(lister):
            return []
        try:
            items = lister() or []
        except Exception:  # noqa: BLE001 - 兜底不可用只放弃近似匹配
            return []
        match = name_match.match_names(name, [item for item in items if isinstance(item, dict)])
        if match.ambiguous_tokens:
            return list(dict.fromkeys(candidate.code for candidate in match.candidates))
        return list(dict.fromkeys(match.codes))

    def _codes_for_name(self, name: str) -> list[str]:
        """把一个名称解析为唯一代码：先 LIKE，再简称/近似。多候选返回多个代码。"""
        candidates = [item for item in self._lookup.search_by_name(name) if _product_code(item)]
        codes = list(dict.fromkeys(_product_code(item) for item in candidates))
        if codes:
            return codes
        return list(dict.fromkeys(self._fuzzy_codes(name)))

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
            candidate_codes = self._codes_for_name(name)
            if len(candidate_codes) != 1:
                if len(candidate_codes) > 1:
                    ambiguous.append(name)
                continue
            code = candidate_codes[0]
            if code in seen:
                continue
            products = self._lookup.query_by_codes([code])
            resolved_name = _product_name(products[0]) if products else name
            references.append(ProductReference(code=code, name=resolved_name or name))
            seen.add(code)

        return references, ambiguous
