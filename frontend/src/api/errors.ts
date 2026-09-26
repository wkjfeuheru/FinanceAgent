/** 从 FastAPI 错误响应中读取可直接展示的业务提示。 */
export function apiErrorMessage(error: any, fallback = '请求失败'): string {
  const detail = error?.response?.data?.detail
  return typeof detail === 'string' && detail ? detail : (error?.message || fallback)
}
