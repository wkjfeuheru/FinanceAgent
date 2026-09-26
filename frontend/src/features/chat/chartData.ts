/**
 * 图表规格派生：把**既有的确定性结构化数据**翻译成可直接渲染的图形规格。
 *
 * ## 为什么不让模型给图数据
 *
 * 正文里的数字受"只能引用工具 JSON"的约束（越界会登记
 * `analysis_number_not_grounded`，见 `orchestration/experts/base.py`）。若让模型
 * 输出图表数据，图上的数字就**绕开**了这套校验，等于在系统里开一个不受约束的
 * 展示面。因此这里只读工具已经算好的结构：`analysis_results`、
 * `technical_analysis`，一个数字都不新增、不改写。
 *
 * 全部函数都是纯函数，便于用 `node --test` 守住"字段缺失不崩、缺数据不出图"。
 * 为了让测试能直接加载本模块，这里只做**相对**导入（Node 不认 `@/` 别名）。
 */

import type { TechnicalIndicatorSet } from '../research/types'

export interface ScoreBar {
  /** 维度标签，如"基本面""技术面"。 */
  metric: string
  value: number
  ratio: number
  /** 展示用数值，保留一位小数。 */
  display: string
}

export interface ScoreItem {
  code: string
  bars: ScoreBar[]
}

export interface ScoreCompareSpec {
  /** 单标的时为空串。 */
  label: string
  items: ScoreItem[]
  /** 多标的对比时用于统一量程的最大值（0~100）。 */
  scaleMax: number
}

/** 振荡指标的超买/超卖参考线。 */
export interface OscillatorZone {
  label: string
  value: number
}

export interface TechnicalOverviewSpec {
  code: string
  /** MACD 柱：从 0 轴向上为 DIF、向下为 DEA，长度按统一量程换算。 */
  macdBars: Array<{ label: string; value: number; ratio: number }>
  /** RSI6 在 0~100 区间内的位置。 */
  oscillator: { label: string; value: number; ratio: number; zones: OscillatorZone[] } | null
  summary: { trend: string; latestPrice: number | null }
}

/** 后端评分字段名 → 展示标签；与 `research/narrative.py` 的 `_SCORE_LABELS` 一致。 */
const SCORE_LABELS: Array<[string, string]> = [
  ['fundamental', '基本面'],
  ['technical', '技术面'],
  ['risk', '风险'],
  ['suitability', '适配度'],
]

/** RSI 的超买/超卖阈值，与 `research/technical.py` 计算 zones 时的取值相同。 */
const RSI_OVERBOUGHT = 80
const RSI_OVERSOLD = 20

function finite(value: unknown): number | null {
  // `null` / `undefined` / 空串必须显式挡掉：`Number(null)` 是 **0**，会把"没有这个
  // 数据"静默画成"数值为 0"（0 分、0% 涨跌都是有意义的取值，不能混用）。
  if (value === null || value === undefined || value === '') return null
  const number = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(number) ? number : null
}

/**
 * 个股评分对比。
 *
 * 比较请求会为每只标的各产出一条 `analysis_results`，因此多标的时每只一组柱；
 * 单标的时退化为"该标的各维度对比"。两者都不新增数字：`total` 不参与，因为
 * 正文已经单独给出综合分，重复展示只会制造两个口径。
 */
export function buildScoreCompareChart(analysisResults: unknown): ScoreCompareSpec | null {
  if (!Array.isArray(analysisResults) || !analysisResults.length) return null

  const items: ScoreItem[] = []
  for (const raw of analysisResults) {
    if (!raw || typeof raw !== 'object') continue
    const record = raw as Record<string, unknown>
    const scores = record.scores
    if (!scores || typeof scores !== 'object') continue

    const bars: ScoreBar[] = []
    for (const [key, label] of SCORE_LABELS) {
      const value = finite((scores as Record<string, unknown>)[key])
      if (value === null) continue
      bars.push({
        metric: label,
        value,
        ratio: Math.max(0, Math.min(100, value)),
        display: value.toFixed(1),
      })
    }
    if (!bars.length) continue

    const codes = (record.request as Record<string, unknown> | undefined)?.stock_codes
    const code = Array.isArray(codes) && codes.length ? String(codes[0]) : ''
    items.push({ code, bars })
  }
  if (!items.length) return null

  const peak = items.reduce(
    (max, item) => item.bars.reduce((inner, bar) => Math.max(inner, bar.value), max),
    0,
  )

  return {
    // 单标的时不给标签（气泡里紧邻的结论卡片已经标了代码），多标的才需要区分。
    label: items.length > 1 ? '多标的评分对比' : '',
    items,
    scaleMax: Math.max(100, peak),
  }
}

/**
 * 技术指标速览。
 *
 * 只画"文字徽标说不清"的部分：MACD 的 DIF/DEA 相对 0 轴的位置，以及 RSI6 在
 * 0~100 区间里离超买/超卖有多远。MA 与 BOLL 已经有徽标数值，不重复画。
 */
export function buildTechnicalOverviewChart(
  technicalAnalysis: unknown,
): TechnicalOverviewSpec[] {
  if (!technicalAnalysis || typeof technicalAnalysis !== 'object') return []

  const specs: TechnicalOverviewSpec[] = []
  for (const [code, raw] of Object.entries(technicalAnalysis as Record<string, unknown>)) {
    if (!raw || typeof raw !== 'object') continue
    const indicators = raw as TechnicalIndicatorSet

    const macd = indicators.MACD?.latest ?? {}
    const dif = finite(macd.DIF)
    const dea = finite(macd.DEA)
    const macdBars: TechnicalOverviewSpec['macdBars'] = []
    const macdPeak = Math.max(Math.abs(dif ?? 0), Math.abs(dea ?? 0))
    if (macdPeak > 0) {
      for (const [label, value] of [['DIF', dif], ['DEA', dea]] as Array<[string, number | null]>) {
        if (value === null) continue
        macdBars.push({ label, value, ratio: Math.min(100, (Math.abs(value) / macdPeak) * 100) })
      }
    }

    const rsi = finite(indicators.RSI?.latest?.RSI6)
    const oscillator =
      rsi === null
        ? null
        : {
            label: 'RSI6',
            value: rsi,
            ratio: Math.max(0, Math.min(100, rsi)),
            zones: [
              { label: `超买 ${RSI_OVERBOUGHT}`, value: RSI_OVERBOUGHT },
              { label: `超卖 ${RSI_OVERSOLD}`, value: RSI_OVERSOLD },
            ],
          }

    if (!macdBars.length && !oscillator) continue

    specs.push({
      code,
      macdBars,
      oscillator,
      summary: {
        trend: String(indicators.summary?.trend ?? ''),
        latestPrice: finite(indicators.summary?.latest_price),
      },
    })
  }
  return specs
}

/**
 * 供持久化使用的"图表最小载荷"。
 *
 * 历史消息只存这些字段就能把图表完整复原；`technical_analysis` 的全量
 * `values` 序列（可能几十 KB）与 K 线原始数组都不入库，避免 metadata 无声膨胀。
 */
export const CHART_PAYLOAD_KEYS = [
  'analysis_results',
  'technical_analysis',
] as const
