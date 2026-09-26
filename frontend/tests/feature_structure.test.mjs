import assert from 'node:assert/strict'
import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import test from 'node:test'

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const src = path.join(frontendRoot, 'src')

test('frontend pages and components are organized by feature', () => {
  for (const feature of ['auth', 'chat', 'portfolio', 'research', 'admin']) {
    assert.ok(existsSync(path.join(src, 'features', feature)), `${feature} feature directory is missing`)
  }

  assert.equal(existsSync(path.join(src, 'views')), false, 'flat views directory should be removed')
  assert.equal(existsSync(path.join(src, 'components')), false, 'flat components directory should be removed')

  const featureFiles = [
    'features/auth/components/LoginView.vue',
    'features/auth/components/ProfilePanel.vue',
    'features/chat/views/ChatView.vue',
    'features/chat/components/ChatWindow.vue',
    'features/chat/components/HistoryPanel.vue',
    'features/chat/components/MessageInput.vue',
    'features/chat/components/MessageList.vue',
    'features/chat/components/ParamDialog.vue',
    'features/portfolio/views/AccountView.vue',
    'features/portfolio/views/PositionsView.vue',
    'features/portfolio/views/ProductMarketView.vue',
    'features/portfolio/components/AllocationCard.vue',
    'features/admin/components/AdminUserPanel.vue',
    'features/admin/components/AdminProductPanel.vue',
  ]
  for (const relativePath of featureFiles) {
    assert.ok(existsSync(path.join(src, relativePath)), `${relativePath} is missing`)
  }
})

test('types live in feature directories without a global type barrel', () => {
  assert.equal(existsSync(path.join(src, 'types', 'index.ts')), false, 'global types barrel should be removed')
  for (const feature of ['auth', 'chat', 'portfolio', 'research', 'admin']) {
    assert.ok(existsSync(path.join(src, 'features', feature, 'types.ts')), `${feature} types are missing`)
  }
})
