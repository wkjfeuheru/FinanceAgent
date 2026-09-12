<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { deactivateTheme, listThemeRegistry, upsertThemeRegistry } from '@/api/chat'
import type { ThemeRegistryEntry } from '@/types'

const entries = ref<ThemeRegistryEntry[]>([])
const loading = ref(false)
const authorized = ref(false)
const saving = ref(false)

const form = ref({ theme_id: '', display_name: '', aliases: '', active: true })

async function load() {
  loading.value = true
  try {
    entries.value = await listThemeRegistry()
    authorized.value = true
  } catch (error: any) {
    // 403 代表当前用户不是管理员，不渲染任何管理入口。
    if (error?.response?.status !== 403) ElMessage.error('主题注册表加载失败')
    authorized.value = false
    entries.value = []
  } finally {
    loading.value = false
  }
}

function parseAliases(text: string): string[] {
  return text.split(/[,，、\s]+/).map(item => item.trim()).filter(Boolean)
}

async function save() {
  const theme_id = form.value.theme_id.trim()
  const display_name = form.value.display_name.trim()
  if (!theme_id || !display_name) {
    ElMessage.warning('请填写主题标识与显示名称')
    return
  }
  saving.value = true
  try {
    const saved = await upsertThemeRegistry({
      theme_id,
      display_name,
      aliases: parseAliases(form.value.aliases),
      active: form.value.active,
    })
    const index = entries.value.findIndex(item => item.theme_id === saved.theme_id)
    if (index >= 0) entries.value[index] = saved
    else entries.value = [...entries.value, saved]
    ElMessage.success('主题已保存')
  } catch {
    ElMessage.error('保存失败，请稍后重试')
  } finally {
    saving.value = false
  }
}

function edit(entry: ThemeRegistryEntry) {
  form.value = {
    theme_id: entry.theme_id,
    display_name: entry.display_name,
    aliases: entry.aliases.join('、'),
    active: entry.active,
  }
}

function reset() {
  form.value = { theme_id: '', display_name: '', aliases: '', active: true }
}

async function deactivate(entry: ThemeRegistryEntry) {
  try {
    await ElMessageBox.confirm(
      `停用「${entry.display_name}」后将不再参与用户主题解析，历史映射保留。`,
      '停用主题',
      { type: 'warning', confirmButtonText: '停用', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deactivateTheme(entry.theme_id)
    entries.value = entries.value.filter(item => item.theme_id !== entry.theme_id)
    ElMessage.success('主题已停用')
  } catch {
    ElMessage.error('停用失败，请稍后重试')
  }
}

onMounted(load)
</script>

<template>
  <el-card v-if="authorized" class="theme-registry" shadow="never" v-loading="loading">
    <div class="registry-heading">
      <div>
        <p class="eyebrow">管理员配置</p>
        <h2>主题注册表</h2>
      </div>
      <span class="entry-count">{{ entries.length }}</span>
    </div>
    <p class="registry-note">用户自由文本主题经此表映射为 theme_id；未登记主题将改走候选搜索。</p>

    <div class="registry-form">
      <el-input v-model="form.theme_id" placeholder="theme_id（如 new_energy）" aria-label="主题标识" />
      <el-input v-model="form.display_name" placeholder="显示名称（如 新能源）" aria-label="显示名称" />
      <el-input v-model="form.aliases" placeholder="别名，用顿号或逗号分隔" aria-label="别名" />
      <div class="form-actions">
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
        <el-button plain @click="reset">清空</el-button>
      </div>
    </div>

    <el-empty v-if="!loading && !entries.length" :image-size="54" description="尚未登记任何主题" />
    <article v-for="entry in entries" :key="entry.theme_id" class="registry-card">
      <div class="registry-title">
        <strong>{{ entry.display_name }}</strong>
        <span class="theme-id">{{ entry.theme_id }}</span>
      </div>
      <p class="aliases">{{ entry.aliases.length ? entry.aliases.join('、') : '无别名' }}</p>
      <div class="registry-actions">
        <el-button size="small" plain @click="edit(entry)">编辑</el-button>
        <el-button size="small" type="danger" plain @click="deactivate(entry)">停用</el-button>
      </div>
    </article>
  </el-card>
</template>

<style scoped>
.theme-registry { border: 1px solid var(--color-border); border-radius: 0; box-shadow: none; }
.registry-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.eyebrow { margin: 0 0 5px; color: var(--color-text-muted); font: 10px/1 var(--font-mono); letter-spacing: .08em; }
h2 { margin: 0; color: var(--color-text); font-size: 15px; }
.entry-count { display: grid; place-items: center; min-width: 24px; height: 24px; background: var(--color-primary-soft); color: var(--color-primary); font: 12px/1 var(--font-mono); }
.registry-note { margin: 10px 0 14px; color: var(--color-text-secondary); font-size: 12px; line-height: 1.6; }
.registry-form { display: grid; gap: 8px; margin-bottom: 14px; }
.form-actions { display: flex; gap: 8px; }
.registry-card { border-top: 1px solid var(--color-border); padding: 13px 0; }
.registry-title { display: flex; align-items: baseline; gap: 8px; color: var(--color-text); }
.theme-id { color: var(--color-text-secondary); font: 12px/1 var(--font-mono); }
.aliases { margin: 6px 0 10px; color: var(--color-text-secondary); font-size: 12px; }
.registry-actions { display: flex; gap: 8px; }
</style>
