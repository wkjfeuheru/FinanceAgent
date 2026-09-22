"""主题注册表解析测试。"""

from finance_agent.research.theme_registry import (
    FallbackThemeRegistry,
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


# ── FallbackThemeRegistry：库内注册不得吞掉内置主题 ──────────────

def test_fallback_list_themes_keeps_builtins_missing_from_primary():
    """库内已注册主题时，内置主题仍须出现在 list_themes。

    回归：早前 list_themes 只在**主读路径为空**时才回退内置表。于是库内一旦登记了
    任何主题，resolve/match_in_text 仍能命中内置主题（它们逐次回退），list_themes
    却只有库内主题 —— 请求解析器的整句扫描走 list_themes，导致内置的 ai_compute
    被静默停用，"推荐人工智能主题股票"退化成候选股比对。
    """
    primary = InMemoryThemeRegistry([
        ThemeEntry(theme_id="consumer_baijiu", display_name="白酒", aliases=["酒类"]),
    ])
    registry = FallbackThemeRegistry(primary, StaticThemeRegistry.builtin())

    ids = [entry.theme_id for entry in registry.list_themes()]

    assert "consumer_baijiu" in ids
    assert "ai_compute" in ids


def test_fallback_primary_entry_overrides_builtin_by_theme_id():
    """库内记录优先：同 theme_id 时以内库版本为准，不出现重复条目。"""
    primary = InMemoryThemeRegistry([
        ThemeEntry(
            theme_id="ai_compute", display_name="人工智能", aliases=["AI"],
            representative_codes=["600519"],
        ),
    ])
    registry = FallbackThemeRegistry(primary, StaticThemeRegistry.builtin())

    matches = [e for e in registry.list_themes() if e.theme_id == "ai_compute"]

    assert len(matches) == 1
    assert matches[0].representative_codes == ["600519"]


def test_fallback_empty_primary_still_exposes_builtins():
    """库内没有任何主题时，行为与纯内置表一致。"""
    registry = FallbackThemeRegistry(InMemoryThemeRegistry(), StaticThemeRegistry.builtin())

    assert registry.resolve("人工智能") == "ai_compute"
    assert registry.match_in_text("推荐人工智能主题股票") is not None
    assert [e.theme_id for e in registry.list_themes()] == ["ai_compute"]
