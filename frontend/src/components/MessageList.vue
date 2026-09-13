<script setup lang="ts">
import { ref, watch, nextTick, computed } from 'vue'
import { User, Headset, Loading } from '@element-plus/icons-vue'
import type {
  ChatMessage,
  ChatResponse,
  ResearchAnalysisResult,
  TechnicalIndicatorSet,
} from '@/types'

const props = defineProps<{
  messages: ChatMessage[]
  loading: boolean
}>()

const listRef = ref<HTMLDivElement | null>(null)

function scrollToBottom() {
  nextTick(() => {
    const el = listRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

watch(
  () => props.messages.length,
  () => scrollToBottom(),
  { flush: 'post' },
)
// 监听最后一条消息内容变化（流式更新滚动）
watch(
  () => props.messages.at(-1)?.content,
  () => scrollToBottom(),
  { flush: 'post' },
)

function formatTime(ts?: string): string {
  if (!ts) return ''
  const d = new Date(ts)
  if (isNaN(d.getTime())) return ts
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function formatNumber(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '—'
  return value.toFixed(2)
}

function scoreEntries(scores: Record<string, number | null>): Array<[string, number | null]> {
  return Object.entries(scores).filter(([key]) => key !== 'total')
}

/** 限制原因码 → 中文说明；未知原因码原样展示，避免隐藏审计信息。 */
const RESTRICTION_TEXT: Record<string, string> = {
  price_history: '缺少足够的历史收盘价',
  fundamental_metrics: '缺少可用的财务或估值指标',
  risk_history: '缺少计算风险所需的行情',
  stock_data: '未获取到该股票数据',
  quote: '缺少最新报价',
  adjusted_history: '缺少前复权历史行情',
  quote_as_of_missing: '报价缺少数据日期',
  stale_quote: '最新报价超过允许的数据新鲜度',
  history_as_of_missing: '历史行情缺少数据日期',
  stale_history: '最新 K 线超过允许的数据新鲜度',
  mixed_report_period: '比较标的的财务报告期不一致',
  fundamental_report_period_missing: '财务数据缺少报告期',
  stale_fundamental_report_period: '财务报告期过于陈旧',
  fundamental_disclosure_date_missing: '财务数据缺少披露日期',
  fundamental_disclosure_before_period: '披露日期早于报告期',
  fundamental_disclosure_in_future: '披露日期晚于评估时点',
  valuation_not_ttm: '估值使用静态 PE 而非 TTM',
  valuation_metrics_missing: '缺少可用估值指标（PE）',
  mixed_sources: '不同数据项来自不同数据源',
  trading_calendar_unavailable: '交易日历不可用，新鲜度按工作日估算',
}

function restrictionText(code: string): string {
  return RESTRICTION_TEXT[code] ?? code
}

/** 结论对应的标的代码；比较请求会为每只标的各出一条结论。 */
function resultCode(result: ResearchAnalysisResult): string {
  return result.request?.stock_codes?.[0] ?? ''
}

/** 收窄分析维度时的视角标注；both（默认）返回空串，不显示徽标。 */
function dimensionLabel(result: ResearchAnalysisResult): string {
  const analysisType = result.request?.analysis_type
  if (analysisType === 'technical') return '技术面视角'
  if (analysisType === 'fundamental') return '基本面视角'
  return ''
}

/** 技术指标卡片数据；K 线不足时后端不产出该标的，这里自然为空。 */
function technicalPanels(
  data?: ChatResponse,
): Array<{ code: string; indicators: TechnicalIndicatorSet }> {
  const raw = data?.technical_analysis
  if (!raw || typeof raw !== 'object') return []
  return Object.entries(raw)
    .filter(([, value]) => Boolean(value) && typeof value === 'object')
    .map(([code, value]) => ({ code, indicators: value as TechnicalIndicatorSet }))
}

/** 关键指标数值拍平为 label/value；缺失项直接跳过，不显示占位。 */
function indicatorRows(
  indicators: TechnicalIndicatorSet,
): Array<{ label: string; value: string }> {
  const rows: Array<{ label: string; value: string }> = []
  const push = (label: string, value: number | string | null | undefined) => {
    if (value === undefined || value === null || value === '') return
    rows.push({ label, value: typeof value === 'number' ? value.toFixed(2) : String(value) })
  }
  const ma = indicators.MA?.latest ?? {}
  push('MA5', ma.MA5)
  push('MA20', ma.MA20)
  const macd = indicators.MACD?.latest ?? {}
  push('MACD DIF', macd.DIF)
  push('MACD DEA', macd.DEA)
  const kdj = indicators.KDJ?.latest ?? {}
  push('KDJ K', kdj.K)
  push('KDJ D', kdj.D)
  const rsi = indicators.RSI?.latest ?? {}
  push('RSI6', rsi.RSI6)
  push('RSI12', rsi.RSI12)
  push('BOLL 带宽', indicators.BOLL?.bandwidth)
  return rows
}

const isEmpty = computed(
  () => props.messages.length === 0 && !props.loading,
)
</script>

<template>
  <div class="message-list" ref="listRef">
    <el-empty v-if="isEmpty" description="暂无对话，开始向投顾提问吧" :image-size="120">
      <template #description>
        <p class="empty-tip">暂无对话，开始向投顾提问吧</p>
        <p class="empty-sub">例如：帮我分析xxx股票的基本面，或制定稳健的资产配置方案</p>
      </template>
    </el-empty>

    <template v-else>
      <div
        v-for="(msg, idx) in messages"
        :key="idx"
        class="message-item"
        :class="msg.role"
      >
        <el-avatar
          :size="36"
          :icon="msg.role === 'user' ? User : Headset"
          class="avatar"
          :class="msg.role === 'user' ? 'avatar-user' : 'avatar-assistant'"
        />
        <div class="bubble-wrap">
          <div class="meta">
            <span class="role-name">
              {{ msg.role === 'user' ? '我' : '智能投顾' }}
            </span>
            <span class="time">{{ formatTime(msg.timestamp) }}</span>
          </div>
          <div class="bubble markdown-body">
            <div v-if="msg.loading && !msg.content && msg.progressSteps?.length" class="progress-panel">
              <div class="progress-title">正在分析</div>
              <div
                v-for="step in msg.progressSteps"
                :key="step.stage"
                class="progress-step"
                :class="step.status"
              >
                <span class="progress-marker">
                  <span v-if="step.status === 'completed'">✓</span>
                  <el-icon v-else class="spin"><Loading /></el-icon>
                </span>
                <span>{{ step.message }}</span>
              </div>
            </div>
            <template v-else-if="msg.loading && !msg.content">
              <span class="typing">
                <el-icon class="typing-dot"><Loading /></el-icon>
                正在分析...
              </span>
            </template>
            <template v-else>
              <div v-if="msg.stage && msg.loading" class="stage-tip">
                <el-icon class="spin"><Loading /></el-icon>
                <span>{{ msg.stage }}</span>
              </div>
              <div v-text="msg.content"></div>
            </template>
          </div>
          <section
            v-for="(result, resultIndex) in msg.data?.analysis_results || []"
            :key="`${idx}-${resultIndex}`"
            class="research-result"
          >
            <div class="research-heading">
              <strong>确定性研究结论：{{ result.action }}</strong>
              <span v-if="resultCode(result)">{{ resultCode(result) }}</span>
              <span v-if="dimensionLabel(result)" class="dimension-badge">{{ dimensionLabel(result) }}</span>
              <span>{{ result.personalization_status === 'personalized' ? '已结合画像' : '研究候选' }}</span>
            </div>
            <div class="research-meta">规则 {{ result.rule_version }} · 数据质量 {{ result.data_quality }}</div>
            <div v-if="scoreEntries(result.scores).length" class="score-list">
              <span v-for="[name, value] in scoreEntries(result.scores)" :key="name">{{ name }} {{ formatNumber(value) }}</span>
            </div>
            <div v-if="result.restrictions?.length" class="restriction-list">
              <span class="restriction-title">限制与提示</span>
              <span v-for="item in result.restrictions" :key="item">{{ restrictionText(item) }}</span>
            </div>
            <div v-if="result.evidence_ids.length" class="evidence-list">
              <span v-for="factId in result.evidence_ids" :key="factId">证据 {{ factId }}</span>
            </div>
          </section>
          <section
            v-for="panel in technicalPanels(msg.data)"
            :key="`${idx}-tech-${panel.code}`"
            class="technical-panel"
          >
            <div class="technical-heading">
              <strong>技术指标：{{ panel.code }}</strong>
              <span v-if="panel.indicators.summary?.trend">{{ panel.indicators.summary.trend }}</span>
            </div>
            <div class="technical-meta">
              最新价 {{ formatNumber(panel.indicators.summary?.latest_price) }}
            </div>
            <div v-if="indicatorRows(panel.indicators).length" class="indicator-grid">
              <span
                v-for="row in indicatorRows(panel.indicators)"
                :key="row.label"
                class="indicator-item"
              >{{ row.label }} {{ row.value }}</span>
            </div>
            <div v-if="panel.indicators.summary?.signals?.length" class="signal-list">
              <span class="signal-title">看多信号</span>
              <span v-for="item in panel.indicators.summary.signals" :key="item">{{ item }}</span>
            </div>
            <div v-if="panel.indicators.summary?.risks?.length" class="risk-list">
              <span class="risk-title">风险信号</span>
              <span v-for="item in panel.indicators.summary.risks" :key="item">{{ item }}</span>
            </div>
          </section>
          <section v-if="msg.data?.pending_leads?.length" class="pending-leads">
            <strong>待核验研究线索</strong>
            <p v-for="lead in msg.data.pending_leads" :key="lead.id">
              {{ lead.stock_code }} · {{ lead.industry || '行业待核验' }} · {{ lead.source_name }}
            </p>
          </section>
        </div>
      </div>

      <!-- 全局加载占位（首次进入无消息时） -->
      <div v-if="loading && messages.length === 0" class="message-item assistant">
        <el-avatar :size="36" :icon="Headset" class="avatar avatar-assistant" />
        <div class="bubble-wrap">
          <div class="meta"><span class="role-name">智能投顾</span></div>
          <div class="bubble">
            <span class="typing">
              <el-icon class="typing-dot"><Loading /></el-icon>
              正在分析...
            </span>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 28px clamp(18px, 4vw, 48px);
  display: flex;
  flex-direction: column;
  gap: 24px;
  scroll-behavior: smooth;
}

.message-item {
  display: flex;
  gap: 10px;
  max-width: 100%;
  align-items: flex-start;
}
.message-item.user {
  flex-direction: row-reverse;
}

.avatar {
  flex-shrink: 0;
}
.avatar-user {
  background: var(--color-primary);
  color: #fff;
}
.avatar-assistant {
  background: var(--color-primary);
  color: #fff;
}

.bubble-wrap {
  display: flex;
  flex-direction: column;
  min-width: 0;
  max-width: 78%;
}
.message-item.user .bubble-wrap {
  align-items: flex-end;
}

.meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
  font-size: 12px;
  color: var(--color-text-muted);
}
.message-item.user .meta {
  flex-direction: row-reverse;
}

.role-name {
  font-weight: 600;
  color: var(--color-text-secondary);
}

.bubble {
  padding: 14px 16px;
  border-radius: 0;
  background: var(--color-assistant-bubble);
  color: var(--color-text);
  box-shadow: none;
  border: 1px solid var(--color-border);
  word-break: break-word;
  white-space: pre-wrap;
}
.message-item.user .bubble {
  background: var(--color-user-bubble);
  color: #fff;
  border-color: var(--color-primary);
}
.message-item.assistant .bubble {
  border-left: 3px solid var(--color-primary);
}

.typing {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--color-text-secondary);
  font-size: 14px;
}
.progress-panel {
  min-width: 260px;
  border-left: 1px solid var(--color-border);
  padding-left: 14px;
}
.progress-title {
  font-weight: 700;
  margin-bottom: 8px;
}
.progress-step {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  color: var(--color-text-secondary);
  font-size: 13px;
}
.progress-step.active {
  color: var(--color-primary);
}
.progress-step.completed {
  color: var(--color-success);
}
.progress-marker {
  width: 18px;
  display: inline-flex;
  justify-content: center;
  flex-shrink: 0;
}
.progress-marker > span { font-family: var(--font-mono); }
.typing-dot {
  animation: pulse 1.2s ease-in-out infinite;
}

.stage-tip {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--color-primary-light);
  background: var(--color-primary-soft);
  padding: 4px 10px;
  border-radius: 0;
  border: 1px solid var(--color-border);
  margin-bottom: 8px;
  width: fit-content;
}
.spin {
  animation: spin 1s linear infinite;
}

.research-result, .pending-leads { margin-top: 8px; max-width: 100%; border: 1px solid var(--color-border); background: var(--color-surface); padding: 10px 12px; font-size: 12px; color: var(--color-text-secondary); }
.research-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; color: var(--color-text); }
.research-heading span { color: var(--color-primary); font: 10px/1 var(--font-mono); letter-spacing: .06em; }
.research-heading span.dimension-badge { padding: 3px 6px; background: var(--color-primary-soft); color: var(--color-primary); }
.research-meta { margin-top: 7px; font-family: var(--font-mono); font-size: 10px; }
.score-list, .evidence-list { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.score-list span, .evidence-list span { padding: 3px 5px; background: var(--color-primary-soft); color: var(--color-primary); font: 10px/1.2 var(--font-mono); }
.restriction-list { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.restriction-list span { padding: 3px 5px; background: rgba(230, 162, 60, 0.12); color: #b8791a; font: 10px/1.2 var(--font-mono); }
.restriction-list .restriction-title { background: transparent; color: var(--color-text-secondary); padding-left: 0; }
.pending-leads strong { color: var(--color-text); }
.pending-leads p { margin: 6px 0 0; }

.technical-panel { margin-top: 8px; max-width: 100%; border: 1px solid var(--color-border); background: var(--color-surface); padding: 10px 12px; font-size: 12px; color: var(--color-text-secondary); }
.technical-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; color: var(--color-text); }
.technical-heading span { color: var(--color-primary); font: 10px/1 var(--font-mono); letter-spacing: .06em; }
.technical-meta { margin-top: 6px; font-family: var(--font-mono); font-size: 10px; }
.indicator-grid { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.indicator-item { padding: 3px 5px; background: var(--color-primary-soft); color: var(--color-primary); font: 10px/1.2 var(--font-mono); }
.signal-list, .risk-list { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.signal-list span, .risk-list span { padding: 3px 5px; font: 10px/1.2 var(--font-mono); }
.signal-list span { background: rgba(103, 194, 58, 0.12); color: var(--color-success); }
.risk-list span { background: rgba(230, 162, 60, 0.12); color: #b8791a; }
.signal-list .signal-title, .risk-list .risk-title { background: transparent; color: var(--color-text-secondary); padding-left: 0; }

.empty-tip {
  color: var(--color-text-secondary);
  font-size: 14px;
  margin: 0;
}
.empty-sub {
  color: var(--color-text-muted);
  font-size: 12px;
  margin: 4px 0 0;
}

@keyframes pulse {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 1; }
}
@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 768px) {
  .message-list {
    padding: 14px 12px;
  }
  .bubble-wrap {
    max-width: 85%;
  }
}
</style>
