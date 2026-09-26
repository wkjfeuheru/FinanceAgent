<script setup lang="ts">
/**
 * 技术指标速览（图形化）。
 *
 * 只画文字徽标说不清的部分：MACD 的 DIF/DEA 相对零轴的位置，以及 RSI6 在
 * 0~100 区间里离超买/超卖有多远。MA 与 BOLL 的数值已有徽标展示，此处不重复，
 * 避免同一屏出现两块内容相同的信息。
 */
import type { TechnicalOverviewSpec } from '@/features/chat/chartData'

defineProps<{ specs: TechnicalOverviewSpec[] }>()

function num(value: number | null, digits = 2): string {
  if (value === null || Number.isNaN(value)) return '—'
  return value.toFixed(digits)
}

function signed(value: number): string {
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(4)}`
}
</script>

<template>
  <section class="chart-card">
    <div class="chart-heading">
      <strong>技术指标速览</strong>
      <span>DIF/DEA 相对零轴 · RSI6 区间位置</span>
    </div>

    <div v-for="spec in specs" :key="spec.code" class="tech-block">
      <div class="tech-title">
        <span class="tech-code">{{ spec.code }}</span>
        <span v-if="spec.summary.trend" class="tech-trend">{{ spec.summary.trend }}</span>
        <span class="tech-price">最新价 {{ num(spec.summary.latestPrice) }}</span>
      </div>

      <div v-if="spec.macdBars.length" class="macd-row">
        <span class="row-label">MACD</span>
        <div class="macd-track">
          <span class="axis" />
          <template v-for="bar in spec.macdBars" :key="bar.label">
            <span
              class="macd-bar"
              :class="bar.value >= 0 ? 'bar-up' : 'bar-down'"
              :style="bar.value >= 0
                ? { left: '50%', width: `${bar.ratio / 2}%` }
                : { right: '50%', width: `${bar.ratio / 2}%` }"
              :title="`${bar.label} ${signed(bar.value)}`"
            />
          </template>
        </div>
        <span class="row-values">
          <span v-for="bar in spec.macdBars" :key="`${bar.label}-v`" class="row-value">
            {{ bar.label }} {{ signed(bar.value) }}
          </span>
        </span>
      </div>

      <div v-if="spec.oscillator" class="osc-row">
        <span class="row-label">{{ spec.oscillator.label }}</span>
        <div class="osc-track">
          <span
            v-for="zone in spec.oscillator.zones"
            :key="zone.label"
            class="osc-zone"
            :style="{ left: `${zone.value}%` }"
            :title="zone.label"
          />
          <span class="osc-marker" :style="{ left: `${spec.oscillator.ratio}%` }" />
        </div>
        <span class="row-values">
          <span class="row-value">{{ spec.oscillator.value.toFixed(1) }}</span>
          <span class="osc-hint">
            <span v-for="zone in spec.oscillator.zones" :key="`${zone.label}-h`">{{ zone.label }}</span>
          </span>
        </span>
      </div>
    </div>

    <p class="chart-note">指标为确定性公式计算结果，仅作研究参考，不构成投资建议。</p>
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
.chart-heading span {
  color: var(--color-text-muted);
  font: 10px/1 var(--font-mono);
  letter-spacing: 0.06em;
}
.tech-block + .tech-block {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--color-border);
}
.tech-title {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 6px;
}
.tech-code {
  color: var(--color-text);
  font: 11px/1.2 var(--font-mono);
  letter-spacing: 0.08em;
}
.tech-trend {
  color: var(--color-primary);
  background: var(--color-primary-soft);
  padding: 2px 5px;
  font-size: 11px;
}
.tech-price {
  color: var(--color-text-muted);
  font: 10px/1.2 var(--font-mono);
  font-variant-numeric: tabular-nums;
}
.macd-row,
.osc-row {
  display: grid;
  grid-template-columns: 44px 1fr auto;
  align-items: center;
  gap: 8px;
  padding: 3px 0;
}
.row-label {
  color: var(--color-text);
  font: 11px/1.2 var(--font-mono);
}
.macd-track {
  position: relative;
  height: 12px;
  background: var(--color-surface-alt);
  overflow: hidden;
}
.axis {
  position: absolute;
  left: 50%;
  top: 0;
  bottom: 0;
  width: 1px;
  background: var(--color-border);
}
.macd-bar {
  position: absolute;
  top: 2px;
  bottom: 2px;
}
.bar-up { background: var(--color-danger); }
.bar-down { background: var(--color-success); }
.osc-track {
  position: relative;
  height: 12px;
  background: var(--color-surface-alt);
}
/* 超买/超卖参考线：RSI 计算 zones 时用的阈值，与后端口径一致 */
.osc-zone {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 1px;
  background: var(--color-border);
}
/* 当前值标记：一条实体竖线，避免用整条填充导致"超买"看起来像满格 */
.osc-marker {
  position: absolute;
  top: -1px;
  bottom: -1px;
  width: 3px;
  background: var(--color-primary);
}
.row-values {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font: 10px/1.2 var(--font-mono);
  font-variant-numeric: tabular-nums;
}
.row-value {
  white-space: nowrap;
}
.osc-hint {
  display: inline-flex;
  gap: 6px;
  color: var(--color-text-muted);
}
.chart-note {
  margin: 8px 0 0;
  font-size: 11px;
  color: var(--color-text-muted);
}

@media (max-width: 768px) {
  .osc-hint {
    display: none;
  }
}
</style>
