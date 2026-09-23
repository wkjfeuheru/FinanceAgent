<script setup lang="ts">
import { computed } from 'vue'
import type { AllocationReview } from '@/types'

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
}

/** 三档占比条：优先用后端给的偏离明细，未提供画像时退化为纯占比。 */
const tierBars = computed<TierBar[]>(() => {
  const deviationByTier = new Map(
    (props.review.deviations || []).map((item) => [item.tier, item]),
  )
  return TIER_ORDER.filter((tier) => (props.review.tiers?.[tier] || 0) > 0).map((tier) => {
    const deviation = deviationByTier.get(tier)
    return {
      tier,
      weight: props.review.tiers[tier] || 0,
      low: deviation?.reference_low ?? null,
      high: deviation?.reference_high ?? null,
      status: deviation?.status || '',
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
      <span>测算波动率 {{ pct(portfolio.volatility) }}</span>
      <span>测算近一年收益 {{ pct(portfolio.expected_return) }}</span>
      <span>测算最大回撤 {{ pct(portfolio.max_drawdown) }}</span>
      <span>分散化比率 {{ num(portfolio.diversification_ratio) }}</span>
      <span>前一大占比 {{ pct(concentration.top1_weight) }}</span>
      <span>前三大合计 {{ pct(concentration.top3_weight) }}</span>
      <span>等效持仓数 {{ num(concentration.effective_n) }}</span>
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
.allocation-note {
  margin: 10px 0 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
