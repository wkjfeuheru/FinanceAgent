<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { User, Lock, EditPen } from '@element-plus/icons-vue'
import { login, register, saveUser } from '@/api/chat'
import type { UserInfo } from '@/types'

const emit = defineEmits<{
  (event: 'logged-in', user: UserInfo): void
}>()

type TabKey = 'login' | 'register'
const activeTab = ref<TabKey>('login')
const submitting = ref(false)

const loginForm = reactive({
  username: '',
  password: '',
})
const registerForm = reactive({
  username: '',
  password: '',
  confirmPassword: '',
  displayName: '',
})

const loginFormRef = ref()
const registerFormRef = ref()

const loginRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

const registerRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 2, max: 32, message: '长度需为 2-32 个字符', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, max: 64, message: '长度需为 6-64 个字符', trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: '请再次输入密码', trigger: 'blur' },
    {
      validator: (_rule: any, value: string, callback: any) => {
        if (value !== registerForm.password) {
          callback(new Error('两次输入的密码不一致'))
        } else {
          callback()
        }
      },
      trigger: 'blur',
    },
  ],
}

const currentTitle = computed(() => (activeTab.value === 'login' ? '欢迎回来' : '创建账号'))
const currentSubtitle = computed(() =>
  activeTab.value === 'login' ? '登录以开始您的智能投顾会话' : '注册一个新账号以使用投顾系统',
)

async function handleLogin() {
  if (!loginFormRef.value) return
  try {
    await loginFormRef.value.validate()
  } catch {
    return
  }
  submitting.value = true
  try {
    const res = await login({
      username: loginForm.username.trim(),
      password: loginForm.password,
    })
    const user: UserInfo = {
      customer_id: res.customer_id,
      username: res.username,
      display_name: res.display_name || res.username,
      token: res.token,
      expires_in: res.expires_in,
      login_at: Date.now(),
    }
    saveUser(user)
    ElMessage.success(`欢迎回来，${user.display_name}！`)
    emit('logged-in', user)
  } catch (err: any) {
    const detail = err?.response?.data?.detail || err?.message || '登录失败'
    ElMessage.error(detail)
  } finally {
    submitting.value = false
  }
}

async function handleRegister() {
  if (!registerFormRef.value) return
  try {
    await registerFormRef.value.validate()
  } catch {
    return
  }
  submitting.value = true
  try {
    await register({
      username: registerForm.username.trim(),
      password: registerForm.password,
      display_name: registerForm.displayName.trim(),
    })
    ElMessage.success('注册成功，请使用新账号登录')
    // 注册成功后切到登录页，预填用户名
    loginForm.username = registerForm.username.trim()
    loginForm.password = ''
    activeTab.value = 'login'
    registerForm.password = ''
    registerForm.confirmPassword = ''
  } catch (err: any) {
    const detail = err?.response?.data?.detail || err?.message || '注册失败'
    ElMessage.error(detail)
  } finally {
    submitting.value = false
  }
}

function switchTab(tab: TabKey) {
  if (submitting.value) return
  activeTab.value = tab
}
</script>

<template>
  <div class="login-view">
    <div class="login-bg"></div>
    <section class="trust-panel">
      <div class="trust-brand"><span>¥</span> FINANCE AGENT / 01</div>
      <h1>让每一次投资决策<br />都有清晰依据。</h1>
      <p>多 Agent 协作完成行情研究、标的筛选、风险画像与资产配置。</p>
      <div class="capability-grid">
        <div><b>01</b><span>多意图识别</span></div>
        <div><b>02</b><span>实时分析链路</span></div>
        <div><b>03</b><span>合规风险控制</span></div>
        <div><b>04</b><span>个性化配置</span></div>
      </div>
      <div class="trust-status"><i></i> 服务状态正常 · 数据安全连接</div>
    </section>
    <div class="login-card">
      <div class="brand-row">
        <div class="brand-mark">¥</div>
        <div class="brand-text">
          <h1 class="brand-title">金融智能投顾系统</h1>
          <p class="brand-sub">多 Agent 协作 · 合规风控 · 资产配置</p>
        </div>
      </div>

      <div class="tabs">
        <button
          class="tab"
          :class="{ active: activeTab === 'login' }"
          @click="switchTab('login')"
        >
          登录
        </button>
        <button
          class="tab"
          :class="{ active: activeTab === 'register' }"
          @click="switchTab('register')"
        >
          注册
        </button>
      </div>

      <div class="form-header">
        <h2 class="form-title">{{ currentTitle }}</h2>
        <p class="form-subtitle">{{ currentSubtitle }}</p>
      </div>

      <!-- 登录表单 -->
      <el-form
        v-if="activeTab === 'login'"
        ref="loginFormRef"
        :model="loginForm"
        :rules="loginRules"
        label-position="top"
        @submit.prevent="handleLogin"
      >
        <el-form-item label="用户名" prop="username">
          <el-input
            v-model="loginForm.username"
            placeholder="请输入用户名"
            :prefix-icon="User"
            clearable
            @keyup.enter="handleLogin"
          />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input
            v-model="loginForm.password"
            type="password"
            placeholder="请输入密码"
            :prefix-icon="Lock"
            show-password
            @keyup.enter="handleLogin"
          />
        </el-form-item>
        <el-button
          type="primary"
          class="submit-btn"
          :loading="submitting"
          @click="handleLogin"
        >
          登录
        </el-button>
      </el-form>

      <!-- 注册表单 -->
      <el-form
        v-else
        ref="registerFormRef"
        :model="registerForm"
        :rules="registerRules"
        label-position="top"
        @submit.prevent="handleRegister"
      >
        <el-form-item label="用户名" prop="username">
          <el-input
            v-model="registerForm.username"
            placeholder="2-32 个字符"
            :prefix-icon="User"
            clearable
          />
        </el-form-item>
        <el-form-item label="显示名称（可选）" prop="displayName">
          <el-input
            v-model="registerForm.displayName"
            placeholder="留空则默认使用用户名"
            :prefix-icon="EditPen"
            clearable
          />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input
            v-model="registerForm.password"
            type="password"
            placeholder="6-64 个字符"
            :prefix-icon="Lock"
            show-password
          />
        </el-form-item>
        <el-form-item label="确认密码" prop="confirmPassword">
          <el-input
            v-model="registerForm.confirmPassword"
            type="password"
            placeholder="请再次输入密码"
            :prefix-icon="Lock"
            show-password
            @keyup.enter="handleRegister"
          />
        </el-form-item>
        <el-button
          type="primary"
          class="submit-btn"
          :loading="submitting"
          @click="handleRegister"
        >
          注册
        </el-button>
      </el-form>

      <p class="hint">
        {{ activeTab === 'login' ? '还没有账号？' : '已有账号？' }}
        <a
          href="javascript:void(0)"
          @click="switchTab(activeTab === 'login' ? 'register' : 'login')"
        >
          {{ activeTab === 'login' ? '立即注册' : '去登录' }}
        </a>
      </p>
    </div>
  </div>
</template>

<style scoped>
.login-view {
  position: relative;
  min-height: 100%;
  width: 100%;
  display: flex;
  align-items: stretch;
  justify-content: center;
  padding: 0;
  overflow: hidden;
}

.login-bg {
  position: absolute;
  inset: 0;
  background-color: var(--color-bg);
  background-image: linear-gradient(var(--color-border) 1px, transparent 1px), linear-gradient(90deg, var(--color-border) 1px, transparent 1px);
  background-size: 96px 96px;
}
.login-bg::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(90deg, rgba(26,60,43,.035), transparent 45%, rgba(244,211,94,.08));
}

.trust-panel { position: relative; z-index: 1; width: min(52%, 720px); padding: clamp(48px, 8vw, 120px); display: flex; flex-direction: column; justify-content: center; border-right: 1px solid var(--color-border); }
.trust-brand { color: var(--color-primary); font: 11px/1 var(--font-mono); letter-spacing: .12em; }
.trust-brand span { display: inline-flex; width: 28px; height: 28px; align-items: center; justify-content: center; margin-right: 10px; background: var(--color-primary); color: #fff; font: 700 15px/1 sans-serif; }
.trust-panel h1 { margin: 56px 0 24px; color: var(--color-primary); font-size: clamp(40px, 5vw, 72px); line-height: 1.03; letter-spacing: -.05em; }
.trust-panel > p { max-width: 540px; margin: 0; color: var(--color-text-secondary); font-size: 16px; line-height: 1.9; }
.capability-grid { display: grid; grid-template-columns: repeat(2, 1fr); margin-top: 56px; border-top: 1px solid var(--color-border); border-left: 1px solid var(--color-border); }
.capability-grid div { display: flex; flex-direction: column; gap: 12px; padding: 20px; border-right: 1px solid var(--color-border); border-bottom: 1px solid var(--color-border); background: rgba(255,255,255,.45); }
.capability-grid b { color: var(--color-text-muted); font: 10px/1 var(--font-mono); }
.capability-grid span { color: var(--color-text); font-weight: 600; }
.trust-status { margin-top: auto; padding-top: 40px; color: var(--color-text-muted); font: 10px/1 var(--font-mono); letter-spacing: .08em; }
.trust-status i { display: inline-block; width: 7px; height: 7px; margin-right: 8px; background: var(--color-success); }

.login-card {
  position: relative;
  z-index: 1;
  width: 100%;
  align-self: center;
  max-width: 440px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 0;
  box-shadow: none;
  padding: 40px;
  margin: 40px clamp(28px, 6vw, 96px);
}

.brand-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 24px;
}

.brand-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: 0;
  background: var(--color-primary);
  color: #fff;
  font-weight: 800;
  font-size: 22px;
  box-shadow: none;
}

.brand-text {
  display: flex;
  flex-direction: column;
}

.brand-title {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  color: var(--color-text);
  letter-spacing: 0.5px;
}

.brand-sub {
  margin: 2px 0 0;
  font-size: 12px;
  color: var(--color-text-muted);
}

.tabs {
  display: flex;
  background: var(--color-surface-alt);
  border: 1px solid var(--color-border);
  border-radius: 0;
  padding: 0;
  margin-bottom: 20px;
}

.tab {
  flex: 1;
  border: none;
  background: transparent;
  padding: 8px 12px;
  border-radius: 0;
  border-right: 1px solid var(--color-border);
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
  color: var(--color-text-secondary);
  transition: all 0.2s ease;
}

.tab:hover {
  color: var(--color-text);
}

.tab.active {
  background: var(--color-primary);
  color: #fff;
  box-shadow: none;
  font-weight: 600;
}

.form-header {
  margin-bottom: 18px;
}

.form-title {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  color: var(--color-text);
}

.form-subtitle {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--color-text-muted);
}

.submit-btn {
  width: 100%;
  height: 42px;
  font-size: 15px;
  font-weight: 600;
  margin-top: 6px;
  border-radius: 2px;
}

.hint {
  margin: 20px 0 0;
  text-align: center;
  font-size: 13px;
  color: var(--color-text-secondary);
}

.hint a {
  color: var(--color-primary);
  text-decoration: none;
  font-weight: 500;
}
.hint a:hover {
  text-decoration: underline;
}

@media (max-width: 900px) {
  .login-view { padding: 24px; }
  .trust-panel { display: none; }
  .login-card {
    margin: 0;
  }
}

@media (max-width: 480px) {
  .login-view { padding: 20px; }
  .login-card {
    padding: 28px 20px 20px;
  }
  .brand-title {
    font-size: 16px;
  }
}
</style>
