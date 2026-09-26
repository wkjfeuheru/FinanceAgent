<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import type { FormInstance, FormRules } from 'element-plus'
import type { ParamField, PendingInput } from '@/features/chat/types'

const props = defineProps<{
  /** 缺参追问载荷；为 null 时不显示弹窗。 */
  pending: PendingInput | null
}>()

const emit = defineEmits<{
  (e: 'submit', answers: Record<string, any>): void
  (e: 'cancel'): void
}>()

const formRef = ref<FormInstance>()
const submitting = ref(false)
const model = reactive<Record<string, any>>({})

const visible = computed({
  get: () => !!props.pending,
  set: (value: boolean) => {
    if (!value) emit('cancel')
  },
})

const fields = computed<ParamField[]>(() => props.pending?.fields ?? [])

/** 必填字段由后端登记，前端只负责渲染与提交前拦截。 */
const rules = computed<FormRules>(() => {
  const result: FormRules = {}
  for (const field of fields.value) {
    if (field.required) {
      result[field.name] = [
        { required: true, message: `请填写${field.label}`, trigger: ['blur', 'change'] },
      ]
    }
  }
  return result
})

// 每次新追问到达时重置表单，避免上一轮的答案泄漏到本次弹窗。
watch(
  () => props.pending,
  (pending) => {
    for (const key of Object.keys(model)) delete model[key]
    for (const field of pending?.fields ?? []) {
      model[field.name] = field.default || ''
    }
    submitting.value = false
    formRef.value?.clearValidate()
  },
  { immediate: true },
)

function placeholderFor(field: ParamField): string {
  if (field.placeholder) return field.placeholder
  if (field.kind === 'choice') return '请选择'
  return field.required ? '必填' : '可选'
}

async function handleSubmit() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  // 只提交非空字段：留空的可选字段不应覆盖已有画像或参数。
  const answers: Record<string, any> = {}
  for (const field of fields.value) {
    const value = model[field.name]
    if (value !== undefined && value !== null && String(value).trim() !== '') {
      answers[field.name] = value
    }
  }
  submitting.value = true
  emit('submit', answers)
}

function handleCancel() {
  emit('cancel')
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    title="需要补充信息"
    width="460px"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    :show-close="false"
    @update:model-value="(value: boolean) => { if (!value) handleCancel() }"
  >
    <p v-if="pending?.question" class="param-note">{{ pending.question }}</p>

    <el-form ref="formRef" :model="model" :rules="rules" label-width="92px" label-position="left">
      <el-form-item
        v-for="field in fields"
        :key="field.name"
        :label="field.label"
        :prop="field.name"
      >
        <el-select
          v-if="field.kind === 'choice'"
          v-model="model[field.name]"
          :placeholder="placeholderFor(field)"
          style="width: 100%"
        >
          <el-option v-for="option in field.options" :key="option" :label="option" :value="option" />
        </el-select>
        <el-input
          v-else
          v-model="model[field.name]"
          :placeholder="placeholderFor(field)"
          clearable
        />
        <span v-if="!field.required" class="optional-tag">可选</span>
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="handleCancel">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="handleSubmit">提交</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.param-note {
  margin: 0 0 16px;
  color: var(--color-text-secondary);
  font-size: 13px;
  line-height: 1.6;
}

.optional-tag {
  margin-left: 8px;
  color: var(--color-text-muted);
  font-size: 11px;
  font-family: var(--font-mono);
}
</style>
