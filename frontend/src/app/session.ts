import type { UserInfo } from '@/features/auth/types'

const STORAGE_KEY = 'finance_cs_user'

/** 保存登录用户信息到 localStorage。 */
export function saveUser(user: UserInfo): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(user))
}

/** 获取当前登录用户信息；不存在或内容无效时返回 null。 */
export function getStoredUser(): UserInfo | null {
  const raw = localStorage.getItem(STORAGE_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as UserInfo
  } catch {
    return null
  }
}

export function getToken(): string {
  return getStoredUser()?.token || ''
}

export function clearUser(): void {
  localStorage.removeItem(STORAGE_KEY)
}
