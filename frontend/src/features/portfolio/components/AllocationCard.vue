<script setup lang="ts">
import { computed } from 'vue'
import type { AllocationReview } from '@/features/portfolio/types'

const props = defineProps<{
  review: AllocationReview
}>()

interface TierBar {
  tier: string
  weight: number
  low: number | null
  high: number | null
  status: string
}

const TIER_ORDER = ['低风险', '中风险', '高风险', '未分类']

const TIER_CLASS: Record<string, string> = {
  低风险: 'tier-low',
  中风险: 'tier-mid',
  高风险: 'tier-high',
  未分类: 'tier-unknown',
}

const STATUS_TEXT: Record<string, string> = {
  below: '低于参考区间',
  within: '处于参考区间',
  above: '高于参考区间',
  absent: '无对应档位标的',
}

/** 三档占比条：保留参考模型要求但当前无持仓的档位（显示为 0 并标注）。 */
const tierBars = computed<TierBar[]>(() => {
  const deviationByTier = new Map(
    (props.review.deviations || []).map((item) => [item.tier, item]),
  )
  const gapByTier = new Map(
    (props.review.optimization?.tier_gaps || []).map((item) => [item.tier, item]),
  )
  return TIER_ORDER.filter((tier) => {
    if ((props.review.tiers?.[tier] || 0) > 0) return true
    // 参考模型要求该档位、但当前无持仓 → 也展示，避免"只有一根 100% 的条"。
    return gapByTier.get(tier)?.status === 'absent'
  }).map((tier) => {
    const gap = gapByTier.get(tier)
    const deviation = deviationByTier.get(tier)
    return {
      tier,
      weight: props.review.tiers?.[tier] || 0,
      low: gap?.reference_low ?? deviation?.reference_low ?? null,
      high: gap?.reference_high ?? deviation?.reference_high ?? null,
      status: gap?.status || deviation?.status || '',
    }
  })
})

function pct(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '—'
  return `${(value * 100).toFixed(2)}%`
}

function num(value: number | null | undefined, digits = 2): string {
  if (value == null || Number.isNaN(value)) return '—'
  return value.toFixed(digits)
}

const concentration = computed(() => props.review.concentration || ({} as any))
const portfolio = computed(() => props.review.portfolio || ({} as any))

/** 优化参考：目标权重、方向与前后对比（旧响应可能缺失）。 */
const optimization = computed(() => props.review.optimization || null)

/** 有方向变化的标的（提高/降低），供"建议调整方向"展示。 */
const suggestions = computed(() =>
  (optimization.value?.targets || []).filter((item) => item.direction !== '维持'),
)

/** 档位层参考方向：高于参考区间→降低，低于/缺失→提高。 */
const tierDirections = computed(() => {
  const gaps = optimization.value?.tier_gaps || []
  return gaps
    .filter((gap) => gap.status === 'above' || gap.status === 'below' || gap.status === 'absent')
    .map((gap) => ({
      tier: gap.tier,
      action: gap.status === 'above' ? '降低' : '提高',
      current: gap.current,
      low: gap.reference_low,
      high: gap.reference_high,
    }))
})

/** 优化前后对比行；指标无变化时不展示（"X% → X%" 只是噪声）。 */
const comparison = computed(() => {
  const before = optimization.value?.before
  const after = optimization.value?.after
  if (!before || !after || before.volatility == null) return []
  const rows = [
    { label: '测算波动率', before: before.volatility, after: after.volatility, fmt: pct },
    { label: '测算近一年收益', before: before.expected_return, after: after.expected_return, fmt: pct },
    { label: '测算最大回撤', before: before.max_drawdown, after: after.max_drawdown, fmt: pct },
  ]
  const changed = rows.some(
    (r) => r.before != null && r.after != null && Math.abs(r.before - r.after) > 1e-6,
  )
  if (!changed) return []
  return rows.map((r) => ({
    label: r.label,
    before: r.fmt(r.before),
    after: r.fmt(r.after),
  }))
})
</script>

<template>
  <section class="allocation-card">
    <div class="allocation-heading">
      <strong>持仓配置诊断</strong>
      <span v-if="review.profile_used">已结合风险偏好 {{ review.risk_preference }}</span>
      <span v-else>未设置风险偏好，仅展示结构与风险暴露</span>
    </div>

    <div class="tier-list">
      <div v-for="bar in tierBars" :key="bar.tier" class="tier-row">
        <span class="tier-label">{{ bar.tier }}</span>
        <div class="tier-track">
          <div
            class="tier-fill"
            :class="TIER_CLASS[bar.tier] || 'tier-unknown'"
            :style="{ width: `${Math.min(bar.weight * 100, 100)}%` }"
          />
        </div>
        <span class="tier-weight">{{ pct(bar.weight) }}</span>
        <span v-if="bar.low != null && bar.high != null" class="tier-band">
          参考 {{ pct(bar.low) }}~{{ pct(bar.high) }}
        </span>
        <span v-if="bar.status" class="tier-status">{{ STATUS_TEXT[bar.status] || bar.status }}</span>
      </div>
    </div>

    <div class="allocation-metrics">
      <span>分散化比率 {{ num(portfolio.diversification_ratio) }}</span>
      <span>前一大占比 {{ pct(concentration.top1_weight) }}</span>
      <span>前三大合计 {{ pct(concentration.top3_weight) }}</span>
      <span>等效持仓数 {{ num(concentration.effective_n) }}</span>
    </div>

    <div v-if="tierDirections.length" class="allocation-suggestions">
      <div class="suggestions-title">档位参考方向（测算口径，非交易指令）</div>
      <div v-for="row in tierDirections" :key="row.tier" class="suggestion-row">
        <span class="suggestion-dir" :class="row.action === '降低' ? 'dir-down' : 'dir-up'">
          {{ row.action }}
        </span>
        <span class="suggestion-name">{{ row.tier }}</span>
        <span class="suggestion-weight">
          当前 {{ pct(row.current) }} · 参考 {{ pct(row.low) }}~{{ pct(row.high) }}
        </span>
      </div>
    </div>

    <div v-if="suggestions.length" class="allocation-suggestions">
      <div class="suggestions-title">持仓参考调整方向（测算口径，非交易指令）</div>
      <div v-for="item in suggestions" :key="item.product_code" class="suggestion-row">
        <span class="suggestion-dir" :class="item.direction === '提高' ? 'dir-up' : 'dir-down'">
          {{ item.direction }}
        </span>
        <span class="suggestion-name">
          {{ item.product_name || item.product_code }}（{{ item.product_code }}）
        </span>
        <span class="suggestion-weight">
          {{ pct(item.current) }} → {{ pct(item.target) }}
        </span>
      </div>
      <div v-if="optimization?.coverage?.uncovered?.length" class="suggestion-coverage">
        其中 {{ optimization?.coverage?.uncovered?.join('、') }} 缺少波动率数据，
        未列入持仓级调整（档位占比仍计入）。
      </div>
    </div>

    <div v-if="comparison.length" class="allocation-compare">
      <span v-for="row in comparison" :key="row.label" class="compare-item">
        {{ row.label }} {{ row.before }} → {{ row.after }}
      </span>
    </div>

    <p class="allocation-note">
      以上为测算口径（对角近似，未考虑相关性），仅供参考，不构成投资建议。
    </p>
  </section>
</template>

<style scoped>
.allocation-card {
  margin-top: 10px;
  padding: 12px 14px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
}
.allocation-heading {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: baseline;
  margin-bottom: 10px;
}
.allocation-heading span {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.tier-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.tier-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}
.tier-label {
  width: 52px;
  flex: 0 0 auto;
  color: var(--el-text-color-regular);
}
.tier-track {
  flex: 1 1 auto;
  height: 10px;
  border-radius: 5px;
  background: var(--el-fill-color);
  overflow: hidden;
}
.tier-fill {
  height: 100%;
  border-radius: 5px;
}
.tier-low { background: #67c23a; }
.tier-mid { background: #e6a23c; }
.tier-high { background: #f56c6c; }
.tier-unknown { background: #909399; }
.tier-weight {
  width: 56px;
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.tier-band,
.tier-status {
  color: var(--el-text-color-secondary);
}
.allocation-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  margin-top: 10px;
  font-size: 12px;
  color: var(--el-text-color-regular);
}
.allocation-suggestions {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed var(--el-border-color-lighter);
}
.suggestions-title {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 6px;
}
.suggestion-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  line-height: 1.8;
}
.suggestion-dir {
  flex: 0 0 auto;
  width: 32px;
  text-align: center;
  border-radius: 4px;
  color: #fff;
}
.dir-up { background: #67c23a; }
.dir-down { background: #f56c6c; }
.suggestion-name {
  flex: 1 1 auto;
  color: var(--el-text-color-regular);
}
.suggestion-weight {
  flex: 0 0 auto;
  font-variant-numeric: tabular-nums;
  color: var(--el-text-color-secondary);
}
.suggestion-coverage {
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.allocation-compare {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  margin-top: 10px;
  font-size: 12px;
  color: var(--el-text-color-regular);
}
.compare-item {
  font-variant-numeric: tabular-nums;
}
.allocation-note {
  margin: 10px 0 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
