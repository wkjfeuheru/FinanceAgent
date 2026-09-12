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
    # 内置主题带代表股，供候选发现直接使用。
    assert registry.resolve("算力") == "ai_compute"
    entry = registry.match_in_text("推荐人工智能主题股票")
    assert entry is not None and entry.representative_codes


def test_match_in_text_prefers_longest_name():
    registry = InMemoryThemeRegistry([
        ThemeEntry(theme_id="ai_compute", display_name="AI", aliases=["人工智能"]),
        ThemeEntry(theme_id="new_energy", display_name="新能源", aliases=["锂电"]),
    ])

    assert registry.match_in_text("推荐几个新能源龙头") is not None
    assert registry.match_in_text("推荐几个新能源龙头").theme_id == "new_energy"
    assert registry.match_in_text("完全不相关的问题") is None


def test_representative_codes_round_trip_and_deactivate_keeps_them():
    registry = InMemoryThemeRegistry()
    registry.upsert(ThemeEntry(
        theme_id="consumer", display_name="消费",
        aliases=["消费龙头"], representative_codes=["600519", "000858"],
    ))

    entry = registry.match_in_text("推荐几个消费龙头股")
    assert entry is not None
    assert entry.representative_codes == ["600519", "000858"]

    assert registry.deactivate("consumer") is True
    assert registry.resolve("消费") is None
    assert registry.match_in_text("推荐几个消费龙头股") is None
