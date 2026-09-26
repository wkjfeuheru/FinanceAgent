import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  renderMarkdown,
  renderMarkdownStreaming,
  splitRenderUnits,
} from '../src/shared/markdown.ts'

/** 验收项 ①：屏幕上不得出现字面的 markdown 语法符号。 */
function assertNoLiteralSyntax(html) {
  // 断言的是**可见文本**里的残留，而不是 HTML 属性/标签名。
  const visible = html.replace(/<[^>]*>/g, '')
  for (const token of ['**', '###', '##', '__']) {
    assert.ok(!visible.includes(token), `可见文本残留了 ${token}：${visible}`)
  }
  assert.ok(!/(^|\n)\s*[-*+]\s/.test(visible), `可见文本残留了列表符号：${visible}`)
}

test('渲染后不再出现字面的 * - # 语法', () => {
  const html = renderMarkdown('### 结论\n- **基本面**良好\n- 技术面`中性`')
  assertNoLiteralSyntax(html)
  assert.match(html, /<h3>结论<\/h3>/)
  assert.match(html, /<strong>基本面<\/strong>/)
  assert.match(html, /<code>中性<\/code>/)
  assert.match(html, /<li>/)
})

test('不解析 raw HTML，标签被转义而不是执行', () => {
  const html = renderMarkdown('<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>')
  // 转义后的 `&lt;script&gt;` 不含 `<script`；而 `onerror=` 作为**纯文本**出现是
  // 正确结果（它不再是属性），所以断言的是"没有可执行的标签/属性语法"。
  assert.ok(!html.includes('<script'), 'raw script 标签不得通过')
  assert.ok(!html.includes('<img'), 'raw img 标签不得通过')
  assert.match(html, /&lt;script&gt;/)
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/)
})

test('图片被降级为纯文本，不产生外链请求', () => {
  const html = renderMarkdown('![走势图](https://example.com/a.png)')
  assert.ok(!html.includes('<img'), '不得产出 img 标签')
  assert.ok(!html.includes('https://example.com'), '不得保留外部地址')
  assert.match(html, /走势图/)
})

test('表格渲染为真实表格（多标的对比依赖它）', () => {
  const html = renderMarkdown('| 指标 | 甲 | 乙 |\n| --- | --- | --- |\n| PE | 20 | 30 |')
  assert.match(html, /<table>/)
  assert.match(html, /<th>指标<\/th>/)
  assert.match(html, /<td>20<\/td>/)
})

test('行中的 -*# 不属于语法，必须原样保留', () => {
  const html = renderMarkdown('贵州茅台-白酒龙头，代码600519#1，权重*')
  assert.match(html, /贵州茅台-白酒龙头/)
  assert.match(html, /600519#1/)
  assert.match(html, /权重\*/)
})

test('空输入与纯空白返回空串，不产出空段落', () => {
  assert.equal(renderMarkdown(''), '')
  assert.equal(renderMarkdown('   \n  '), '')
})

test('分块：续行并入上一块，行首结构标记另起一块', () => {
  const units = splitRenderUnits('## 大盘\n- a\n- b\n')
  assert.deepEqual(
    units.map((unit) => unit.text),
    ['## 大盘', '- a', '- b'],
  )
})

test('分块：源码以换行结尾时末块收尾，停在行中间时未收尾', () => {
  assert.equal(splitRenderUnits('- a\n')[0].complete, true)
  assert.equal(splitRenderUnits('- a')[0].complete, false)
  // 标题与分隔线在换行处语义即终止，停在行尾也可安全渲染。
  assert.equal(splitRenderUnits('## 大盘')[0].complete, true)
  assert.equal(splitRenderUnits('---')[0].complete, true)
})

test('流式：标题立即渲染，未闭合的段落保持纯文本', () => {
  const mid = renderMarkdownStreaming('## 大盘\n这是**粗')
  assert.match(mid.settled, /<h2>大盘<\/h2>/)
  assert.equal(mid.pending, '这是**粗')
  assert.ok(!mid.settled.includes('粗'), '未闭合的块不得进入 settled')
})

test('流式：换行即视为该块结束，可以渲染', () => {
  const done = renderMarkdownStreaming('这是**粗体**\n')
  assert.match(done.settled, /<strong>粗体<\/strong>/)
  assert.equal(done.pending, '')
})

test('流式定稿与一次性渲染结果一致', () => {
  const source = '### 结论\n- **基本面**良好\n\n小结：注意风险。'
  const streamed = renderMarkdownStreaming(source, true)
  assert.equal(streamed.pending, '')
  assert.equal(streamed.settled, renderMarkdown(source))
})

test('流式中间态：已定块与未定块拼接不丢原文', () => {
  const source = '第一段。\n\n第二段**未完'
  const partial = renderMarkdownStreaming(source)
  assert.equal(partial.settled, '<p>第一段。</p>')
  assert.equal(partial.pending, '第二段**未完')
})
