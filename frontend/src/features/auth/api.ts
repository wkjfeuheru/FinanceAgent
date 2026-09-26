/** 用户认证 API。 */

import { http } from '@/api/client'
import { clearUser } from '@/app/session'
import type { LoginRequest, LoginResponse, RegisterRequest, RegisterResponse, UserInfo } from './types'

export async function register(req: RegisterRequest): Promise<RegisterResponse> {
  const { data } = await http.post<RegisterResponse>('/register', req)
  return data
}

export async function login(req: LoginRequest): Promise<LoginResponse> {
  const { data } = await http.post<LoginResponse>('/login', req)
  return data
}

export async function logout(): Promise<void> {
  try {
    await http.post('/logout')
  } catch {
    // 登出请求失败时仍清除本地会话。
  } finally {
    clearUser()
  }
}

export async function getCurrentUser(): Promise<UserInfo> {
  const { data } = await http.get<UserInfo>('/me')
  return data
}
