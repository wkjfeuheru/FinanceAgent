<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { PieChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import type { EChartsOption } from 'echarts'

use([CanvasRenderer, PieChart, TitleComponent, TooltipComponent, LegendComponent])

const props = defineProps<{
  weights: Record<string, number>
}>()

const palette = [
  '#1e3a8a',
  '#3b5bdb',
  '#60a5fa',
  '#fbbf24',
  '#10b981',
  '#f97316',
  '#ef4444',
  '#8b5cf6',
  '#06b6d4',
  '#84cc16',
]

const chartData = computed(() => {
  const entries = Object.entries(props.weights || {})
  if (!entries.length) return []
  return entries.map(([name, value], idx) => ({
    name,
    value: Number(value),
    itemStyle: { color: palette[idx % palette.length] },
  }))
})

const hasData = computed(() => chartData.value.length > 0)

const option = computed<EChartsOption>(() => ({
  tooltip: {
    trigger: 'item',
    formatter: (params: any) => {
      const pct = (params.percent ?? 0).toFixed(2)
      return `${params.name}<br/>权重：<b>${pct}%</b>`
    },
  },
  legend: {
    orient: 'horizontal',
    bottom: 0,
    type: 'scroll',
    textStyle: { fontSize: 11, color: '#64748b' },
    itemWidth: 10,
    itemHeight: 10,
  },
  series: [
    {
      name: '资产配置',
      type: 'pie',
      radius: ['42%', '68%'],
      center: ['50%', '42%'],
      avoidLabelOverlap: true,
      itemStyle: {
        borderRadius: 6,
        borderColor: '#fff',
        borderWidth: 2,
      },
      label: {
        show: true,
        formatter: '{b}\n{d}%',
        fontSize: 11,
        color: '#475569',
      },
      emphasis: {
        label: { show: true, fontSize: 13, fontWeight: 'bold' },
        itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.2)' },
      },
      data: chartData.value,
    },
  ],
}))
</script>

<template>
  <div class="allocation-chart">
    <div class="chart-header">
      <span class="chart-title">资产配置建议</span>
    </div>
    <div v-if="hasData" class="chart-body">
      <v-chart :option="option" autoresize class="chart" />
    </div>
    <div v-else class="chart-empty">
      <el-empty description="暂无配置数据" :image-size="70">
        <template #description>
          <p class="empty-text">暂无配置数据</p>
          <p class="empty-sub">向投顾咨询后将展示配置方案</p>
        </template>
      </el-empty>
    </div>
  </div>
</template>

<style scoped>
.allocation-chart {
  display: flex;
  flex-direction: column;
}

.chart-header {
  padding: 14px 16px;
  border-bottom: 1px solid var(--color-border);
}

.chart-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--color-text);
}

.chart-body {
  width: 100%;
  height: 280px;
  padding: 8px;
}

.chart {
  width: 100%;
  height: 100%;
}

.chart-empty {
  height: 220px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.empty-text {
  margin: 0;
  font-size: 13px;
  color: var(--color-text-secondary);
}
.empty-sub {
  margin: 4px 0 0;
  font-size: 11px;
  color: var(--color-text-muted);
}
</style>
