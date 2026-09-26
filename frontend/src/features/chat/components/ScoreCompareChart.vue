<script setup lang="ts">
/**
 * 个股评分对比。
 *
 * 多标的时按维度成行、每只标的一根柱（横向分组柱图）；单标的时退化为该标的
 * 各维度对比。数值取自 `analysis_results[].scores`，不参与图形的 `total` 由
 * `chartData` 过滤——正文已单独给出综合分，重复展示会制造两个口径。
 */
import type { ScoreCompareSpec } from '@/features/chat/chartData'

defineProps<{ spec: ScoreCompareSpec }>()

/** 柱色按标的下标循环取用；三色足够区分对比请求的常规标的数。 */
const BAR_CLASSES = ['bar-a', 'bar-b', 'bar-c']

function colorOf(index: number): string {
  return BAR_CLASSES[index % BAR_CLASSES.length]
}

function seriesName(code: string, index: number): string {
  return code || `标的 ${index + 1}`
}

/** 中性参考线：评分区间中值，用来判断某维度是偏高还是偏低。 */
const NEUTRAL = 50
const neutralLeft = `${NEUTRAL}%`
</script>

<template>
  <section class="chart-card">
    <div class="chart-heading">
      <strong>{{ spec.label || '评分明细' }}</strong>
      <span v-if="spec.items.length > 1">
        <i v-for="(item, index) in spec.items" :key="item.code || index" class="legend">
          <i class="legend-dot" :class="colorOf(index)" />{{ seriesName(item.code, index) }}
        </i>
      </span>
      <span v-else>满分 {{ spec.scaleMax }}</span>
    </div>

    <div
      v-for="(metric, metricIndex) in spec.items[0].bars.map((bar) => bar.metric)"
      :key="metric"
      class="metric-row"
    >
      <span class="metric-label">{{ metric }}</span>
      <div class="metric-track">
        <span class="neutral" :style="{ left: neutralLeft }" />
        <div
          v-for="(item, itemIndex) in spec.items"
          :key="item.code || itemIndex"
          class="metric-series"
        >
          <span
            v-if="item.bars[metricIndex]"
            class="bar"
            :class="colorOf(itemIndex)"
            :style="{ width: `${item.bars[metricIndex].ratio}%` }"
          />
        </div>
      </div>
      <span class="metric-values">
        <span
          v-for="(item, itemIndex) in spec.items"
          :key="`${item.code || itemIndex}-value`"
          class="metric-value"
        >{{ item.bars[metricIndex]?.display ?? '—' }}</span>
      </span>
    </div>

    <p class="chart-note">
      评分为确定性规则测算结果（{{ NEUTRAL }} 为区间中值），不构成投资建议。
    </p>
  </section>
</template>

<style scoped>
.chart-card {
  margin-top: 8px;
  max-width: 100%;
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  padding: 10px 12px;
  font-size: 12px;
  color: var(--color-text-secondary);
}
.chart-heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  color: var(--color-text);
  margin-bottom: 8px;
}
.chart-heading > span {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 10px;
  color: var(--color-text-muted);
  font: 10px/1 var(--font-mono);
  letter-spacing: 0.06em;
}
.legend {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-style: normal;
}
.legend-dot {
  width: 8px;
  height: 8px;
  display: inline-block;
}
.metric-row {
  display: grid;
  grid-template-columns: 56px 1fr auto;
  align-items: center;
  gap: 8px;
  padding: 3px 0;
}
.metric-label {
  color: var(--color-text);
  white-space: nowrap;
}
.metric-track {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.metric-series {
  height: 8px;
  background: var(--color-surface-alt);
  overflow: hidden;
}
.bar {
  display: block;
  height: 100%;
}
.bar-a { background: var(--color-primary); }
.bar-b { background: var(--color-success); }
.bar-c { background: var(--color-text-muted); }
.neutral {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 1px;
  background: var(--color-border);
  z-index: 1;
}
.metric-values {
  display: inline-flex;
  gap: 8px;
  font: 11px/1.2 var(--font-mono);
  font-variant-numeric: tabular-nums;
}
.metric-value {
  min-width: 34px;
  text-align: right;
}
.chart-note {
  margin: 8px 0 0;
  font-size: 11px;
  color: var(--color-text-muted);
}
</style>
