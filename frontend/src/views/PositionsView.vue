<script setup lang="ts">
/** 持仓：展示份额/成本/市值/浮动盈亏，支持部分或全部卖出，以及一键清仓。 */
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Sell, Delete } from '@element-plus/icons-vue'
import { createOrder, liquidate, listPositions } from '@/api/portfolio'
import type { AccountSnapshot, PositionView, UserInfo } from '@/types'
import {
  describeLimitation, formatMoney, formatPercent, formatShare, formatShares,
  formatSignedMoney, makeIdempotencyKey, pnlClass,
} from '@/utils/format'

defineProps<{ currentUser: UserInfo }>()

const loading = ref(false)
const positions = ref<PositionView[]>([])
const account = ref<AccountSnapshot | null>(null)

const sellVisible = ref(false)
const selling = ref(false)
const target = ref<PositionView | null>(null)
const sellShares = ref<number>(0)
const sellAll = ref(false)
const sellKey = ref('')

/** 存在无法定价的持仓时，市值口径不完整，需要显式提示。 */
const pricingIssues = computed(() => account.value?.pricing_issues ?? [])
const hasUnpriced = computed(() => account.value?.market_value_complete === false)

async function load() {
  loading.value = true
  try {
    const result = await listPositions()
    positions.value = result.positions
    account.value = result.account
  } catch (error: any) {
    ElMessage.error(error?.message || '持仓加载失败')
  } finally {
    loading.value = false
  }
}

function openSell(item: PositionView) {
  target.value = item
  sellShares.value = item.shares
  sellAll.value = false
  sellKey.value = makeIdempotencyKey('sell')
  sellVisible.value = true
}

async function confirmSell() {
  if (!target.value) return
  if (!sellAll.value && (!sellShares.value || sellShares.value <= 0)) {
    ElMessage.warning('请输入大于 0 的赎回份额')
    return
  }
  selling.value = true
  try {
    const result = await createOrder({
      product_code: target.value.product_code,
      side: 'sell',
      shares: sellAll.value ? undefined : sellShares.value,
      all: sellAll.value,
      idempotency_key: sellKey.value,
    })
    ElMessage.success(
      `赎回成功：${result.order.shares} 份，到账 ${formatMoney(result.order.net_amount)} 元，`
      + `已实现盈亏 ${formatSignedMoney(result.order.realized_pnl)} 元`,
    )
    sellVisible.value = false
    await load()
  } catch (error: any) {
    ElMessage.error(error?.message || '赎回失败')
  } finally {
    selling.value = false
  }
}

/** 一键清仓：二次确认后清空全部持仓。 */
async function confirmLiquidate() {
  if (!positions.value.length) {
    ElMessage.info('当前没有持仓')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确定要清仓全部 ${positions.value.length} 只持仓吗？将按最新净值全部赎回，该操作不可撤销。`,
      '一键清仓',
      { confirmButtonText: '确认清仓', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  loading.value = true
  try {
    const result = await liquidate()
    const failedCodes = Object.keys(result.failed)
    ElMessage.success(
      `清仓完成：${result.cleared_codes.length} 只已赎回，`
      + `到账 ${formatMoney(result.total_cash_in)} 元，`
      + `已实现盈亏 ${formatSignedMoney(result.total_realized_pnl)} 元`,
    )
    if (failedCodes.length) {
      ElMessage.warning(
        `以下商品未能清仓：${failedCodes
          .map(code => `${code}（${describeLimitation(result.failed[code])}）`)
          .join('；')}`,
      )
    }
    await load()
  } catch (error: any) {
    ElMessage.error(error?.message || '清仓失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="page">
    <header class="page-head">
      <div>
        <p class="eyebrow">PORTFOLIO / POSITIONS</p>
        <h2>我的持仓</h2>
        <p class="page-note">按最新净值估值；模拟交易数据，不构成投资建议。</p>
      </div>
      <div class="page-tools">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button
          type="danger"
          :icon="Delete"
          :disabled="!positions.length"
          :loading="loading"
          @click="confirmLiquidate"
        >
          一键清仓
        </el-button>
      </div>
    </header>

    <!-- 口径不完整时必须明示，避免用户以为市值就是全部资产 -->
    <el-alert
      v-if="hasUnpriced"
      type="warning"
      show-icon
      :closable="false"
      class="warn-alert"
      title="部分持仓缺少可用净值，市值口径不完整"
      :description="`以下商品未计入市值：${pricingIssues.join('、')}`"
    />

    <div v-if="account" class="stat-row">
      <div class="stat">
        <span class="stat-label">持仓市值</span>
        <strong>{{ formatMoney(account.market_value, '元') }}</strong>
      </div>
      <div class="stat">
        <span class="stat-label">浮动盈亏</span>
        <strong :class="pnlClass(account.position_pnl)">{{ formatSignedMoney(account.position_pnl) }} 元</strong>
      </div>
      <div class="stat">
        <span class="stat-label">持仓成本</span>
        <strong>{{ formatMoney(account.position_cost, '元') }}</strong>
      </div>
      <div class="stat">
        <span class="stat-label">持仓数量</span>
        <strong>{{ account.position_count }} 只</strong>
      </div>
    </div>

    <el-card shadow="never" v-loading="loading" class="table-card">
      <el-empty
        v-if="!loading && !positions.length"
        :image-size="60"
        description="暂无持仓，去「商品」页面申购"
      />
      <el-table v-else :data="positions" stripe style="width: 100%">
        <el-table-column label="商品" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="product-cell">
              <strong>{{ row.product_name || row.product_code }}</strong>
              <small class="mono">{{ row.product_code }}</small>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="份额" width="110" align="right">
          <template #default="{ row }">{{ formatShares(row.shares) }}</template>
        </el-table-column>
        <el-table-column label="持仓成本" width="120" align="right">
          <template #default="{ row }">{{ formatMoney(row.cost_amount) }}</template>
        </el-table-column>
        <el-table-column label="平均成本" width="100" align="right">
          <template #default="{ row }">{{ row.avg_cost.toFixed(4) }}</template>
        </el-table-column>
        <el-table-column label="最新净值" width="110" align="right">
          <template #default="{ row }">
            <span v-if="row.nav != null">{{ row.nav.toFixed(4) }}</span>
            <el-tag v-else type="warning" size="small" effect="plain">净值缺失</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="市值" width="120" align="right">
          <template #default="{ row }">{{ formatMoney(row.market_value) }}</template>
        </el-table-column>
        <el-table-column label="浮动盈亏" width="130" align="right">
          <template #default="{ row }">
            <span :class="pnlClass(row.unrealized_pnl)">{{ formatSignedMoney(row.unrealized_pnl) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="收益率" width="100" align="right">
          <template #default="{ row }">
            <span :class="pnlClass(row.return_rate)">{{ formatPercent(row.return_rate) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="占比" width="90" align="right">
          <template #default="{ row }">{{ formatShare(row.weight) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="110" align="center" fixed="right">
          <template #default="{ row }">
            <el-tooltip
              :disabled="row.pricing_status === 'priced'"
              content="缺少可用净值，暂不可赎回"
              placement="top"
            >
              <span>
                <el-button
                  size="small"
                  :icon="Sell"
                  :disabled="row.pricing_status !== 'priced'"
                  @click="openSell(row)"
                >
                  卖出
                </el-button>
              </span>
            </el-tooltip>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 卖出弹窗 -->
    <el-dialog v-model="sellVisible" title="赎回确认" width="440px">
      <div v-if="target" class="sell-form">
        <p class="sell-title">
          <strong>{{ target.product_name || target.product_code }}</strong>
          <span class="mono">{{ target.product_code }}</span>
        </p>
        <dl class="sell-meta">
          <div><dt>持有份额</dt><dd>{{ formatShares(target.shares) }} 份</dd></div>
          <div><dt>最新净值</dt><dd>{{ target.nav?.toFixed(4) ?? '—' }}</dd></div>
          <div><dt>持仓成本</dt><dd>{{ formatMoney(target.cost_amount) }} 元</dd></div>
          <div><dt>浮动盈亏</dt>
            <dd :class="pnlClass(target.unrealized_pnl)">
              {{ formatSignedMoney(target.unrealized_pnl) }} 元（{{ formatPercent(target.return_rate) }}）
            </dd>
          </div>
        </dl>

        <el-form label-width="90px" label-position="left">
          <el-form-item label="全部赎回">
            <el-switch v-model="sellAll" />
          </el-form-item>
          <el-form-item v-if="!sellAll" label="赎回份额">
            <el-input-number
              v-model="sellShares"
              :min="0.01"
              :max="target.shares"
              :step="100"
              :precision="2"
              style="width: 100%"
            />
          </el-form-item>
        </el-form>
      </div>
      <template #footer>
        <el-button @click="sellVisible = false">取消</el-button>
        <el-button type="primary" :loading="selling" @click="confirmSell">确认赎回</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.page { flex: 1; min-height: 0; overflow-y: auto; padding: 24px; }
.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
.eyebrow { margin: 0 0 6px; color: var(--color-text-muted); font: 10px/1 var(--font-mono); letter-spacing: .1em; }
.page-head h2 { margin: 0 0 6px; font-size: 20px; color: var(--color-text); }
.page-note { margin: 0; color: var(--color-text-secondary); font-size: 12px; }
.page-tools { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.warn-alert { border-radius: 0; margin-bottom: 12px; }

.stat-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }
.stat { display: flex; flex-direction: column; gap: 6px; border: 1px solid var(--color-border); background: var(--color-surface); padding: 14px 16px; }
.stat-label { color: var(--color-text-muted); font-size: 11px; }
.stat strong { font-size: 18px; font-weight: 600; }

.table-card { border: 1px solid var(--color-border); border-radius: 0; box-shadow: none; }
.product-cell { display: flex; flex-direction: column; gap: 2px; }
.product-cell small { color: var(--color-text-muted); font-size: 11px; }
.mono { color: var(--color-text-muted); font: 11px/1 var(--font-mono); }

.sell-form { display: flex; flex-direction: column; gap: 12px; }
.sell-title { margin: 0; display: flex; align-items: baseline; gap: 8px; }
.sell-meta { margin: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 8px 16px; }
.sell-meta div { display: flex; flex-direction: column; gap: 2px; }
.sell-meta dt { color: var(--color-text-muted); font-size: 11px; }
.sell-meta dd { margin: 0; font-size: 13px; }

/* 盈亏配色：涨绿跌红（A 股习惯），0 与缺失用中性色 */
:deep(.pnl-up) { color: var(--color-success); }
:deep(.pnl-down) { color: var(--color-danger); }
:deep(.pnl-flat) { color: var(--color-text-secondary); }

@media (max-width: 980px) {
  .stat-row { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 768px) {
  .page { padding: 16px 12px; }
  .page-head { flex-direction: column; }
  .page-tools { width: 100%; }
}
</style>
