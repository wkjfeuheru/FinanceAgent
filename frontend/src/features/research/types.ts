/** 单个标的的技术指标（展示层，来自股票专家的确定性计算）。 */
export interface TechnicalIndicatorSet {
  /** 移动均线：latest 含 MA5/MA10/MA20/MA60。 */
  MA?: {
    latest?: Record<string, number>
    trend?: Record<string, string>
    position?: string
  }
  /** MACD：信号与背离仅在有明确结论时给出。 */
  MACD?: {
    latest?: Record<string, number>
    signal?: string | null
    divergence?: string | null
    trend?: string
  }
  KDJ?: {
    latest?: Record<string, number>
    signal?: string | null
    zone?: string
  }
  RSI?: {
    latest?: Record<string, number>
    zones?: Record<string, string>
  }
  BOLL?: {
    latest?: Record<string, number>
    bandwidth?: number
    position?: string
  }
  WR?: {
    latest?: Record<string, number>
    zones?: Record<string, string>
  }
  /** 汇总：综合趋势、看多信号、风险信号与最新价。 */
  summary?: {
    trend?: string
    signals?: string[]
    risks?: string[]
    latest_price?: number
  }
}

/** 技术指标按标的代码组织；K 线不足时该标的会缺失。 */
export interface TechnicalAnalysis {
  [code: string]: TechnicalIndicatorSet
}

/** 产品专家确定性研究结果；保留索引签名以兼容历史字典响应。 */
export interface ProductAnalysisPayload {
  schema_version?: string
  type?: 'single' | 'question' | 'deep_dive' | 'comparison' | (string & {})
  product_codes?: string[]
  products?: ProductAssessmentPayload[]
  assessments?: ProductAssessmentPayload[]
  evidence_ids?: string[]
  data_quality?: 'complete' | 'warning' | 'critical_missing' | (string & {})
  personalization_status?: 'personalized' | 'research_candidate' | (string & {})
  ambiguities?: string[]
  report?: string
  [key: string]: any
}

export interface ProductAssessmentPayload {
  code: string
  name?: string
  risk_level?: string | null
  risk_source?: string
  suitability_status?: 'matched' | 'unmatched' | 'unavailable' | 'not_evaluated' | (string & {})
  suitability_reasons?: string[]
  usable_for_comparison?: boolean
  missing_fields?: string[]
  restrictions?: string[]
  evidences?: Record<string, ProductFieldEvidencePayload>
  [key: string]: any
}

export interface ProductFieldEvidencePayload {
  field: string
  value?: any
  source?: string
  as_of?: string
  freshness?: 'fresh' | 'stale' | 'unknown' | (string & {})
  fact_id?: string
  [key: string]: any
}

/** 已计算的确定性研究结论；与待核验线索分离。 */
export interface ResearchAnalysisResult {
  action: '关注' | '观望' | '规避' | '数据不足'
  data_quality: 'complete' | 'warning' | 'critical_missing'
  rule_version: string
  scores: Record<string, number | null>
  evidence_ids: string[]
  personalization_status: 'personalized' | 'research_candidate'
  restrictions: string[]
  /** 该结论对应的研究请求；比较请求会为每只标的各出一条结论。 */
  request?: {
    stock_codes?: string[]
    /** 分析维度：both（默认）不改变呈现，收窄时前端标注视角。 */
    analysis_type?: 'fundamental' | 'technical' | 'both'
  }
}
