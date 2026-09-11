<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getThemeLeads, reviewThemeLead } from '@/api/chat'
import type { ThemeLead } from '@/types'

const themeId = ref('ai_compute')
const leads = ref<ThemeLead[]>([])
const loading = ref(false)
const authorized = ref(false)

function dateLabel(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString('zh-CN')
}

async function load() {
  const value = themeId.value.trim()
  if (!value) return
  loading.value = true
  try {
    leads.value = await getThemeLeads(value)
    authorized.value = true
  } catch (error: any) {
    // 403 代表当前用户不是管理员，不渲染任何审核入口。
    if (error?.response?.status !== 403) ElMessage.error('待审核线索加载失败')
    authorized.value = false
    leads.value = []
  } finally {
    loading.value = false
  }
}

async function review(lead: ThemeLead, decision: 'approve' | 'reject') {
  loading.value = true
  try {
    await reviewThemeLead(lead.id, {
      decision,
      evidence_expires_at: lead.evidence_expires_at,
      note: decision === 'approve' ? '管理员已核验证据' : '管理员未通过证据核验',
    })
    leads.value = leads.value.filter(item => item.id !== lead.id)
    ElMessage.success(decision === 'approve' ? '线索已通过审核' : '线索已拒绝')
  } catch {
    ElMessage.error('审核未完成，请稍后重试')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <el-card v-if="authorized" class="review-queue" shadow="never" v-loading="loading">
    <div class="queue-heading">
      <div>
        <p class="eyebrow">管理员审核</p>
        <h2>待核验研究线索</h2>
      </div>
      <span class="lead-count">{{ leads.length }}</span>
    </div>
    <p class="queue-note">线索通过前不会进入候选评分、排序或行动结论。</p>

    <div class="theme-filter">
      <el-input v-model="themeId" aria-label="主题标识" @keyup.enter="load" />
      <el-button type="primary" :loading="loading" @click="load">查询</el-button>
    </div>

    <el-empty v-if="!loading && !leads.length" :image-size="54" description="当前主题没有待审核线索" />
    <article v-for="lead in leads" :key="lead.id" class="lead-card">
      <div class="lead-title">
        <strong>{{ lead.stock_code }}</strong><span>{{ lead.industry || '行业待核验' }}</span>
      </div>
      <p class="lead-source">{{ lead.source_name }} · {{ lead.source_class }}</p>
      <a :href="lead.source_uri" target="_blank" rel="noreferrer">查看来源证据</a>
      <blockquote>{{ lead.evidence_excerpt }}</blockquote>
      <p class="expiry">证据到期：{{ dateLabel(lead.evidence_expires_at) }}</p>
      <div class="review-actions">
        <el-button size="small" type="success" plain @click="review(lead, 'approve')">通过</el-button>
        <el-button size="small" type="danger" plain @click="review(lead, 'reject')">拒绝</el-button>
      </div>
    </article>
  </el-card>
</template>

<style scoped>
.review-queue { border: 1px solid var(--color-border); border-radius: 0; box-shadow: none; }
.queue-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.eyebrow { margin: 0 0 5px; color: var(--color-text-muted); font: 10px/1 var(--font-mono); letter-spacing: .08em; }
h2 { margin: 0; color: var(--color-text); font-size: 15px; }
.lead-count { display: grid; place-items: center; min-width: 24px; height: 24px; background: var(--color-primary-soft); color: var(--color-primary); font: 12px/1 var(--font-mono); }
.queue-note { margin: 10px 0 14px; color: var(--color-text-secondary); font-size: 12px; line-height: 1.6; }
.theme-filter { display: flex; gap: 8px; margin-bottom: 12px; }
.lead-card { border-top: 1px solid var(--color-border); padding: 13px 0; }
.lead-title { display: flex; align-items: baseline; gap: 8px; color: var(--color-text); }
.lead-title strong { font-family: var(--font-mono); }
.lead-title span, .lead-source, .expiry { color: var(--color-text-secondary); font-size: 12px; }
.lead-source { margin: 6px 0; }
a { color: var(--color-primary); font-size: 12px; }
blockquote { margin: 9px 0; padding-left: 9px; border-left: 2px solid var(--color-primary-light); color: var(--color-text-secondary); font-size: 12px; line-height: 1.55; }
.expiry { margin: 0 0 10px; font-family: var(--font-mono); }
.review-actions { display: flex; gap: 8px; }
</style>
