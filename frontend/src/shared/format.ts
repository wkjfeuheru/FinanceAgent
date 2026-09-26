/** 模拟交易页面的展示格式化工具。 */

/** 金额：千分位 + 两位小数；无法解析返回 '—'。 */
export function formatMoney(value: number | null | undefined, suffix = ''): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  const text = Number(value).toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
  return suffix ? `${text} ${suffix}` : text
}

/** 带正负号的金额（盈亏场景）。 */
export function formatSignedMoney(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  const sign = Number(value) > 0 ? '+' : ''
  return `${sign}${formatMoney(value)}`
}

/** 百分比数值（后端已是 5.2 表示 5.2%）：带符号与 %。 */
export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  const sign = Number(value) > 0 ? '+' : ''
  return `${sign}${Number(value).toFixed(2)}%`
}

/**
 * 比率转百分比：产品库的收益与回撤以小数存储（0.126 表示 12.6%），
 * 与账户口径的百分比数值不同，必须分开格式化，否则会把 12.6% 显示成 0.13%。
 */
export function formatRatioPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return formatPercent(Number(value) * 100)
}

/**
 * 无符号百分比：用于占比这类"份额"而非"变动"的数值。
 * ``formatPercent`` 会加 ``+``，用在占比上会把静态比例误读成涨跌。
 */
export function formatShare(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${Number(value).toFixed(2)}%`
}

/** 份额：两位小数。 */
export function formatShares(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return Number(value).toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

/** 费率（后端小数 0.015 → 1.50%）。 */
export function formatRate(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '未披露'
  return `${(Number(value) * 100).toFixed(2)}%`
}

/** 日期时间：精确到分钟。 */
export function formatDateTime(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  })
}

/** 盈亏配色类名。 */
export function pnlClass(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value) || Number(value) === 0) {
    return 'pnl-flat'
  }
  return Number(value) > 0 ? 'pnl-up' : 'pnl-down'
}

/** 后端限制项代码 → 中文提示。 */
const LIMITATION_TEXT: Record<string, string> = {
  'fee_unavailable:subscription_fee': '申购费率未披露，本次成交按 0 费率计算。',
  'fee_unavailable:redemption_fee': '赎回费率未披露，本次成交按 0 费率计算。',
  pricing_unavailable: '缺少可用净值，无法计算市值与盈亏。',
  product_offline: '商品已下架，不可申购；既有持仓仍可赎回。',
  'account_service_failed': '账户数据暂不可用。',
}

export function describeLimitation(code: string): string {
  return LIMITATION_TEXT[code] || code
}

/** 生成幂等键：同一笔操作重试时复用，避免重复扣款。 */
export function makeIdempotencyKey(prefix: string): string {
  const random = Math.random().toString(36).slice(2, 10)
  return `${prefix}-${Date.now()}-${random}`
}
