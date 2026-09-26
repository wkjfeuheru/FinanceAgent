import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  buildScoreCompareChart,
  buildTechnicalOverviewChart,
} from '../src/features/chat/chartData.ts'

test('评分对比：多标的每只一组柱，并标注对比标题', () => {
  const spec = buildScoreCompareChart([
    { scores: { fundamental: 62, technical: 55, risk: 70, suitability: 80, total: 66 }, request: { stock_codes: ['600519'] } },
    { scores: { fundamental: 48, technical: 60, risk: 65, suitability: 75, total: 60 }, request: { stock_codes: ['000858'] } },
  ])
  assert.ok(spec)
  assert.equal(spec.label, '多标的评分对比')
  assert.equal(spec.items.length, 2)
  assert.equal(spec.items[0].code, '600519')
  assert.deepEqual(spec.items[0].bars.map((bar) => bar.metric), ['基本面', '技术面', '风险', '适配度'])
})

test('评分对比：total 不参与图形，避免与正文综合分成两个口径', () => {
  const spec = buildScoreCompareChart([{ scores: { fundamental: 62, total: 66 } }])
  assert.ok(spec)
  assert.deepEqual(spec.items[0].bars.map((bar) => bar.metric), ['基本面'])
})

test('评分对比：缺失维度跳过，全缺失则不画图', () => {
  const partial = buildScoreCompareChart([{ scores: { fundamental: 62, technical: null } }])
  assert.ok(partial)
  assert.deepEqual(partial.items[0].bars.map((bar) => bar.metric), ['基本面'])

  assert.equal(buildScoreCompareChart([{ scores: { fundamental: null } }]), null)
  assert.equal(buildScoreCompareChart([{ scores: {} }]), null)
  assert.equal(buildScoreCompareChart([]), null)
  assert.equal(buildScoreCompareChart(null), null)
})

test('评分对比：单标的时不加对比标题', () => {
  const spec = buildScoreCompareChart([{ scores: { fundamental: 62 } }])
  assert.ok(spec)
  assert.equal(spec.label, '')
})

test('评分对比：超出 0~100 的值被夹紧，不溢出轨道', () => {
  const spec = buildScoreCompareChart([{ scores: { fundamental: 150 } }])
  assert.ok(spec)
  assert.equal(spec.items[0].bars[0].ratio, 100)
  assert.equal(spec.items[0].bars[0].display, '150.0')
})

test('技术速览：MACD 两柱按自身量程换算，RSI6 带超买超卖参考线', () => {
  const specs = buildTechnicalOverviewChart({
    '600519': {
      MACD: { latest: { DIF: 0.4, DEA: -0.2 } },
      RSI: { latest: { RSI6: 82, RSI12: 70 } },
      summary: { trend: '多头', latest_price: 1444.42 },
    },
  })
  assert.equal(specs.length, 1)
  const spec = specs[0]
  assert.equal(spec.code, '600519')
  assert.equal(spec.macdBars.length, 2)
  assert.equal(spec.macdBars[0].ratio, 100)
  assert.equal(spec.macdBars[1].ratio, 50)
  assert.ok(spec.oscillator)
  assert.equal(spec.oscillator.value, 82)
  assert.deepEqual(spec.oscillator.zones.map((zone) => zone.value), [80, 20])
  assert.equal(spec.summary.trend, '多头')
  assert.equal(spec.summary.latestPrice, 1444.42)
})

test('技术速览：缺 MACD 与 RSI 的标的被跳过，不画空块', () => {
  assert.deepEqual(buildTechnicalOverviewChart({ '600519': { MA: { latest: { MA5: 1 } } } }), [])
  assert.deepEqual(buildTechnicalOverviewChart({ '600519': {} }), [])
  assert.deepEqual(buildTechnicalOverviewChart({}), [])
  assert.deepEqual(buildTechnicalOverviewChart(null), [])
})

test('技术速览：只有 RSI 时也能出图（MACD 柱为空但振荡条有效）', () => {
  const specs = buildTechnicalOverviewChart({ '000858': { RSI: { latest: { RSI6: 12 } } } })
  assert.equal(specs.length, 1)
  assert.deepEqual(specs[0].macdBars, [])
  assert.equal(specs[0].oscillator?.ratio, 12)
})

test('技术速览：DIF 与 DEA 同为 0 时不产生零长柱', () => {
  const specs = buildTechnicalOverviewChart({
    '600519': { MACD: { latest: { DIF: 0, DEA: 0 } }, RSI: { latest: { RSI6: 50 } } },
  })
  assert.equal(specs.length, 1)
  assert.deepEqual(specs[0].macdBars, [])
  assert.ok(specs[0].oscillator)
})
