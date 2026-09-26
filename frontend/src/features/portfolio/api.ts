/** 模拟交易 API 封装：商品货架、账户、持仓、下单、清仓、记录。 */

import { http } from '@/api/client'
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
} from '@/features/portfolio/types'

const PORTFOLIO_BASE = '/portfolio'

/** 商品货架 */
export async function listProducts(productType = 'fund'): Promise<ProductShelfResponse> {
  const { data } = await http.get<ProductShelfResponse>(`${PORTFOLIO_BASE}/products`, {
    params: { product_type: productType },
  })
  return data
}

/** 单品详情 */
export async function getProduct(code: string): Promise<ProductView> {
  const { data } = await http.get<ProductView>(
    `${PORTFOLIO_BASE}/products/${encodeURIComponent(code)}`,
  )
  return data
}

/** 账户数据面板 */
export async function getAccount(): Promise<AccountSnapshot> {
  const { data } = await http.get<AccountSnapshot>(`${PORTFOLIO_BASE}/account`)
  return data
}

/** 持仓明细 */
export async function listPositions(): Promise<PositionListResponse> {
  const { data } = await http.get<PositionListResponse>(`${PORTFOLIO_BASE}/positions`)
  return data
}

/** 充值 */
export async function deposit(payload: DepositRequest): Promise<DepositResponse> {
  const { data } = await http.post<DepositResponse>(`${PORTFOLIO_BASE}/deposit`, payload)
  return data
}

/** 下单（买入/卖出） */
export async function createOrder(payload: OrderRequest): Promise<TradeResponse> {
  const { data } = await http.post<TradeResponse>(`${PORTFOLIO_BASE}/orders`, payload)
  return data
}

/** 一键清仓 */
export async function liquidate(): Promise<LiquidationResponse> {
  const { data } = await http.post<LiquidationResponse>(`${PORTFOLIO_BASE}/liquidate`, {})
  return data
}

/** 成交记录 */
export async function listOrders(limit = 100): Promise<OrderListResponse> {
  const { data } = await http.get<OrderListResponse>(`${PORTFOLIO_BASE}/orders`, {
    params: { limit },
  })
  return data
}

/** 资金流水 */
export async function listTransactions(limit = 100): Promise<TransactionListResponse> {
  const { data } = await http.get<TransactionListResponse>(`${PORTFOLIO_BASE}/transactions`, {
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
