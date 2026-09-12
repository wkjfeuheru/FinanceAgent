"""主题注册表解析测试。"""

from finance_agent.research.theme_registry import (
    InMemoryThemeRegistry,
    StaticThemeRegistry,
    ThemeEntry,
)


def test_inmemory_registry_resolves_display_name_alias_and_id():
    registry = InMemoryThemeRegistry([
        ThemeEntry(theme_id="ai_compute", display_name="AI算力", aliases=["人工智能", "算力"]),
    ])

    assert registry.resolve("AI算力") == "ai_compute"
    assert registry.resolve("人工智能") == "ai_compute"
    assert registry.resolve("算力") == "ai_compute"
    assert registry.resolve("ai_compute") == "ai_compute"
    assert registry.resolve("白酒") is None


def test_inactive_theme_is_not_resolved():
    registry = InMemoryThemeRegistry([
        ThemeEntry(theme_id="ai_compute", display_name="AI算力", aliases=["算力"], active=False),
    ])

    assert registry.resolve("算力") is None
    assert registry.list_themes() == []


def test_builtin_registry_covers_ai_compute_aliases():
    registry = StaticThemeRegistry.builtin()

    assert registry.resolve("人工智能") == "ai_compute"
    assert registry.resolve("AI") == "ai_compute"
