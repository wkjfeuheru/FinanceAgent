from finance_agent.tools.market_data import (
    EastMoneyMarketData, _try_match_sector, _is_quality_match,
    _extract_sector_keyword,
)

em = EastMoneyMarketData()

# 逐步跟踪 _try_match_sector 对 "新能源" 的执行
keyword = "新能源"
print(f"=== 跟踪 _try_match_sector('{keyword}') ===")

# Step 1: find_sector_by_keyword("新能源")
result1 = em.find_sector_by_keyword("新能源")
print(f"Step 1 - find('新能源'): {result1}")

# Step 2: 渐进式移除
print(f"\nStep 2 - 渐进式移除:")
for i in range(1, len(keyword) - 1):
    sub = keyword[i:]
    print(f"  i={i}: sub='{sub}' (len={len(sub)}, need>=2)")
    result = em.find_sector_by_keyword(sub)
    print(f"    find('{sub}'): {result}")
    if result:
        quality = _is_quality_match(keyword, sub, result["name"])
        print(f"    quality_check: {quality} (matched='{sub}' in '{result['name']}', min_len={max(2, len(keyword)*0.6)})")

# Step 3: 完整 _try_match_sector
print(f"\nStep 3 - _try_match_sector('{keyword}'):")
final = _try_match_sector(em, keyword)
print(f"  结果: {final}")

# 额外测试：直接搜"能源"
print(f"\n=== 直接测试 find_sector_by_keyword('能源') ===")
r = em.find_sector_by_keyword("能源")
print(f"  结果: {r}")
