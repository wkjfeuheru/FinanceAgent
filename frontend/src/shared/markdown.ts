/**
 * 用户可见正文的 Markdown 渲染。
 *
 * ## 为什么需要这一层
 *
 * 领域专家写出的正文是模型自由撰写的 Markdown，而界面此前用 `v-text` 当**纯文本**
 * 渲染，于是 `**粗体**`、`- 项目`、`### 标题` 的原始符号直接显示给用户。渲染层是
 * 让这些符号消失在屏幕上的**唯一**保证——提示词只能降低模型产出装饰性 Markdown
 * 的倾向，不是强制机制（见 `domains/research/expert/assemble.py` 的同类论述）。
 *
 * ## 白名单
 *
 * 允许：段落 / 小标题 / 列表 / 加粗 / 行内代码 / 表格。
 * 禁止：raw HTML（`html: false`，且本次渲染结果只经 `v-html` 进入**助手气泡**）、
 * 图片（`_no_images` 规则）：行情图与在线图片都不该由模型输出决定，且本系统
 * 离线可用，任何外链图片只会变成裂图。
 *
 * ## 流式渲染
 *
 * 定稿答复是按块经 SSE `delta` 下发的，因此渲染要能容忍中间态。做法是
 * **逐块推进**：已完成的块渲染成 HTML，末尾那个尚未确定结束的块保持纯文本，
 * 避免未闭合的 `**` 在收尾瞬间从字面文本跳变成粗体。
 */

import MarkdownIt from 'markdown-it'
import type { Token } from 'markdown-it'

/** 行首的"结构性标记"：命中意味着这一行自成块，不可能是上一块的续行。 */
// 注意：**不带 `g` 标志**。带 `g` 的 RegExp 有 `lastIndex` 状态，连续调用 `.test()`
// 会交替返回 true/false，从而把块边界判错（这里踩过一次）。
const LINE_START_MARKER = /^(?: {0,3}(?:#{1,6}\s|[-*+]\s|\d{1,9}[.)]\s|>|\||```|~~~|(?:[-*_])\s*(?:[-*_]\s*){2,}))/

/**
 * 单独一行即可判定的块：ATX 标题与分隔线。
 *
 * 它们的语义**在换行处就终止**（标题正文不会被下一行续写），因此哪怕源码停在
 * 行中间也能安全渲染。其余块（段落、列表、表格）必须等到换行才能确定收尾。
 */
const SELF_CONTAINED_LINE =
  /^(?: {0,3}#{1,6}(?:\s|$)| {0,3}(?:[-*_])\s*(?:[-*_]\s*){2,}$)/

/** 围栏代码块的起止行；围栏内部的换行不属于块边界。 */
const FENCE = /^ {0,3}(?:```|~~~)/

const markdown = new MarkdownIt({
  // 绝不解析 raw HTML：模型输出（以及 FAQ 原文）都不是可信 HTML 来源。
  html: false,
  linkify: true,
  breaks: false,
})

/**
 * 丢弃图片：把 `![说明](url)` 降级为纯文本 `说明`。
 *
 * 用自定义规则替换默认 `image` 规则，而不是在渲染后删除 `<img>`——后者会因为
 * 内联规则已把 token 记成 `image` 而留下空标签。
 */
// 形参显式标注类型：`tokens[idx]` 在不带 `noUncheckedIndexedAccess` 时是 `Token`，
// 但省略标注会让 `tokens` 落到隐式 any，渲染器规则签名校验因此失败。
markdown.renderer.rules.image = (tokens: Token[], idx: number): string => {
  const token = tokens[idx]
  // `attrGet` 返回 `string | number | null`，统一收敛成字符串。
  const alt = token.attrGet('alt')
  return token.content || (alt === null ? '' : String(alt))
}

/**
 * 把源码切成"渲染单元"，并标出最后一个是否已确定结束。
 *
 * 边界规则：
 * - **空行**是硬边界；
 * - 行首结构标记（`#`、`-`、`|`…）另起一块；
 * - 当前块**已自成一体**时（标题/分隔线/围栏代码），后续非空行必然是新块；
 * - 否则不含行首标记的非空行是**续行**（`**粗体**` 单独成块会与紧跟其后的
 *   `- 列表` 割裂，必须让列表接走这段文字）。
 *
 * | 条件 | 含义 |
 * | --- | --- |
 * | 空行 | 边界 |
 * | `LINE_START_MARKER` | 边界 |
 * | 当前块 `SELF_CONTAINED_LINE` | 边界 |
 * | 以上皆非 | 续行 |
 */
export function splitRenderUnits(source: string): Array<{ text: string; complete: boolean }> {
  const value = source || ''
  if (!value) return []

  const units: string[] = []
  let current = ''
  let currentIsSelfContained = false
  const flush = () => {
    if (current !== '') {
      units.push(current)
      current = ''
      currentIsSelfContained = false
    }
  }

  const lines = value.split('\n')
  // 末尾 `\n` 之后是一个空串——那是"已换行"的证据，不是一行内容。
  const lastIsVirtual = value.endsWith('\n')
  const contentLines = lastIsVirtual ? lines.slice(0, -1) : lines

  for (const line of contentLines) {
    if (!line.trim()) {
      flush()
      continue
    }
    const continues =
      current !== '' && !currentIsSelfContained && !LINE_START_MARKER.test(line)
    if (continues) {
      current += `\n${line}`
      continue
    }
    flush()
    current = line
    currentIsSelfContained = SELF_CONTAINED_LINE.test(line) || FENCE.test(line)
  }
  flush()

  // 末块是否已收尾：
  // - 源码以 `\n` 结尾 → 该行已写完，收尾；
  // - 末行是标题/分隔线 → 语义在换行处终止，收尾；
  // - 否则它停在行中间，仍可能被后续 delta 改写，不能提前渲染。
  const lastContentLine = contentLines.length ? contentLines[contentLines.length - 1] : ''
  const trailingPartial = !lastIsVirtual && !SELF_CONTAINED_LINE.test(lastContentLine)

  return units.map((text, index) => ({
    text,
    complete: !(index === units.length - 1 && trailingPartial),
  }))
}

/** 渲染一段 Markdown 为 HTML。只允许经 `v-html` 进入助手气泡。 */
export function renderMarkdown(source: string): string {
  const value = String(source ?? '')
  if (!value.trim()) return ''
  return markdown.render(value).trim()
}

export interface StreamingRender {
  /** 已确定结束的块渲染结果；可直接 `v-html`。 */
  settled: string
  /** 末尾尚未确定的块，按**纯文本**呈现（不经 HTML）。 */
  pending: string
}

/**
 * 流式渲染：已完成块 → HTML，末尾未定块 → 纯文本。
 *
 * 每个已定块**独立渲染**再拼接，而不是把各块拼回一整段源码重新渲染——后者会让
 * 块之间重新发生 Markdown 结合（实测 `- 项` 与紧随其后的段落被并成一个列表项），
 * 使流式结果与 `renderMarkdown` 不一致。
 */
export function renderMarkdownStreaming(source: string, isFinal = false): StreamingRender {
  const units = splitRenderUnits(source)
  if (!units.length) return { settled: '', pending: '' }

  const settledUnits: string[] = []
  let pending = ''
  units.forEach((unit, index) => {
    const isLast = index === units.length - 1
    // 未确定结束的末块**不计入 settled**：它仍可能长出新的一行并被重新归类。
    if (isLast && !unit.complete && !isFinal) pending = unit.text
    else settledUnits.push(unit.text)
  })

  return {
    settled: settledUnits.map(renderMarkdown).filter(Boolean).join('\n'),
    pending,
  }
}
