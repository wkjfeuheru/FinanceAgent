<script setup lang="ts">
import { computed } from 'vue'
import { User, Wallet, Money, Clock, Aim } from '@element-plus/icons-vue'
import type { ProfileResponse } from '@/types'

const props = defineProps<{
  profile: ProfileResponse | null
  loading: boolean
}>()

const riskColor = computed(() => {
  const r = props.profile?.risk_preference || ''
  if (r.includes('低') || r.includes('R1') || r.includes('R2')) return 'success'
  if (r.includes('中') || r.includes('R3')) return 'warning'
  if (r.includes('高') || r.includes('R4') || r.includes('R5')) return 'danger'
  return 'info'
})

function formatBudget(v?: number): string {
  if (!v && v !== 0) return '—'
  if (v >= 10000) return `¥${(v / 10000).toFixed(2)} 万`
  return `¥${v.toLocaleString()}`
}
</script>

<template>
  <el-card class="profile-panel" shadow="never">
    <template #header>
      <div class="panel-header">
        <el-icon color="#1e3a8a" size="18"><User /></el-icon>
        <span class="panel-title">用户画像</span>
      </div>
    </template>

    <el-skeleton v-if="loading" :rows="5" animated />

    <template v-else-if="profile">
      <div class="profile-grid">
        <div class="profile-item">
          <div class="item-label">
            <el-icon><Aim /></el-icon>
            <span>风险偏好</span>
          </div>
          <div class="item-value">
            <el-tag :type="riskColor" effect="light" size="small">
              {{ profile.risk_preference || '未评估' }}
            </el-tag>
          </div>
        </div>

        <div class="profile-item">
          <div class="item-label">
            <el-icon><Wallet /></el-icon>
            <span>预算金额</span>
          </div>
          <div class="item-value value-num">
            {{ formatBudget(profile.budget_amount) }}
          </div>
        </div>

        <div class="profile-item">
          <div class="item-label">
            <el-icon><Money /></el-icon>
            <span>关注股票</span>
          </div>
          <div class="item-value">
            <template v-if="profile.stock_codes && profile.stock_codes.length">
              <el-tag
                v-for="code in profile.stock_codes"
                :key="code"
                size="small"
                effect="plain"
                class="stock-tag"
              >
                {{ code }}
              </el-tag>
            </template>
            <span v-else class="placeholder">未设置</span>
          </div>
        </div>

        <div class="profile-item">
          <div class="item-label">
            <el-icon><Clock /></el-icon>
            <span>持有时间</span>
          </div>
          <div class="item-value">
            {{ profile.holding_period || '未设置' }}
          </div>
        </div>

        <div class="profile-item">
          <div class="item-label">
            <el-icon><Aim /></el-icon>
            <span>投资目标</span>
          </div>
          <div class="item-value">
            {{ profile.investment_goal || '未设置' }}
          </div>
        </div>
      </div>

      <div v-if="profile.updated_at" class="updated-at">
        更新时间：{{ profile.updated_at }}
      </div>
    </template>

    <el-empty v-else description="暂无用户画像" :image-size="80" />
  </el-card>
</template>

<style scoped>
.profile-panel {
  border-radius: var(--radius-md);
  border: none;
  box-shadow: var(--shadow-card);
}
.profile-panel :deep(.el-card__header) {
  padding: 14px 16px;
  border-bottom: 1px solid var(--color-border);
}
.profile-panel :deep(.el-card__body) {
  padding: 16px;
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 8px;
}
.panel-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--color-text);
}

.profile-grid {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.profile-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.item-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--color-text-muted);
}
.item-label .el-icon {
  font-size: 14px;
  color: var(--color-primary-light);
}

.item-value {
  font-size: 14px;
  color: var(--color-text);
  font-weight: 500;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
.value-num {
  font-size: 16px;
  font-weight: 700;
  color: var(--color-primary);
}

.stock-tag {
  font-family: 'Courier New', monospace;
  font-weight: 600;
}

.placeholder {
  color: var(--color-text-muted);
  font-weight: 400;
}

.updated-at {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed var(--color-border);
  font-size: 11px;
  color: var(--color-text-muted);
}
</style>
