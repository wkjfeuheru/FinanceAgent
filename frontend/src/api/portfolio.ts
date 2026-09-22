/** 模拟交易 API 封装：商品货架、账户、持仓、下单、清仓、记录。 */

import axios from 'axios'
import { getToken } from '@/api/chat'
import type {
  AccountSnapshot,
  DepositRequest,
  DepositResponse,
  LiquidationResponse,
  OrderListResponse,
  OrderRequest,
  PositionListResponse,
  ProductShelfResponse,
  ProductView,
  TradeResponse,
  TransactionListResponse,
} from '@/types'

const http = axios.create({
  baseURL: '/api/portfolio',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

// 与 chat.ts 一致：自动注入 Bearer token。身份只来自 token，前端不传 customer_id。
http.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// 后端把业务失败写成 detail（含错误码），统一提取成可读信息。
http.interceptors.response.use(
  (response) => response,
  (error) => {
    const detail = error?.response?.data?.detail
    const message = typeof detail === 'string' && detail ? detail : (error?.message || '请求失败')
    return Promise.reject(new Error(message))
  },
)

/** 商品货架 */
export async function listProducts(productType = 'fund'): Promise<ProductShelfResponse> {
  const { data } = await http.get<ProductShelfResponse>('/products', {
    params: { product_type: productType },
  })
  return data
}

/** 单品详情 */
export async function getProduct(code: string): Promise<ProductView> {
  const { data } = await http.get<ProductView>(`/products/${encodeURIComponent(code)}`)
  return data
}

/** 账户数据面板 */
export async function getAccount(): Promise<AccountSnapshot> {
  const { data } = await http.get<AccountSnapshot>('/account')
  return data
}

/** 持仓明细 */
export async function listPositions(): Promise<PositionListResponse> {
  const { data } = await http.get<PositionListResponse>('/positions')
  return data
}

/** 充值 */
export async function deposit(payload: DepositRequest): Promise<DepositResponse> {
  const { data } = await http.post<DepositResponse>('/deposit', payload)
  return data
}

/** 下单（买入/卖出） */
export async function createOrder(payload: OrderRequest): Promise<TradeResponse> {
  const { data } = await http.post<TradeResponse>('/orders', payload)
  return data
}

/** 一键清仓 */
export async function liquidate(): Promise<LiquidationResponse> {
  const { data } = await http.post<LiquidationResponse>('/liquidate', {})
  return data
}

/** 成交记录 */
export async function listOrders(limit = 100): Promise<OrderListResponse> {
  const { data } = await http.get<OrderListResponse>('/orders', { params: { limit } })
  return data
}

/** 资金流水 */
export async function listTransactions(limit = 100): Promise<TransactionListResponse> {
  const { data } = await http.get<TransactionListResponse>('/transactions', {
    params: { limit },
  })
  return data
}

export default {
  listProducts,
  getProduct,
  getAccount,
  listPositions,
  deposit,
  createOrder,
  liquidate,
  listOrders,
  listTransactions,
}
