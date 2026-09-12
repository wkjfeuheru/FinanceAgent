# Product Analysis P0 实施记录（main 分支版）

> **状态：已实施完成（2026-09-12，main 分支）。** 本文件是**产品（非 RAG）部分**的实施与完工记录。
>
> 原始计划写在 RAG 分支 `codex/product-rag-document-workspace` 上，把产品研究改造与文档
> 向量检索混在同一份计划里（其 Task 1 引用了仅存在于该分支的 `PRODUCT_LIBRARY_FIELDS` 与
> `006_product_document_rag_hardening.sql`）。产品部分已按决策选择性移植到 main，**不含任何
> RAG 内容**；原始计划的复选框未回填，属历史记录。

**目标：** 将 `product_analysis` 从依赖 ReAct 工具调用的自由文本专家，升级为基于产品库事实、
字段新鲜度与用户画像门槛的确定性产品研究专家，同时保持聊天 API 兼容。

**架构：** 产品引用解析、批量事实读取、规则评估与报告渲染组成无状态的
`ProductResearchPipeline`。专家只负责把编排状态转换为流水线请求、写回强类型结果与事实快照；
旧 `product_analysis` 字段作为兼容投影保留。

## 不变量（均已实现并有测试）

- 产品数据只来自 PostgreSQL 产品库；没有事实即返回数据不足，**不使用 LLM 补写事实**。
- 产品风险等级来源优先；标准化失败返回数据不足，**不根据收益或波动率推断 R1–R5**。
- 持仓/业绩超过 freshness 阈值时披露来源与日期，但**不据此生成收益、风险或比较结论**。
- 只有风险偏好与持有期限同时存在时才输出"匹配/不匹配"；否则固定为 `research_candidate`。
- 输出不含交易指令、买卖建议或"适合你"措辞。

## main 分支上的交付物

- `finance_agent/product_research/`：`contracts.py`（请求/证据/评估/结果）、`resolver.py`
  （代码优先、名称其次、**歧义不静默取第一条**）、`rules.py`（风险与期限的适配规则）、
  `pipeline.py`（无状态流水线与报告渲染）。
- `finance_agent/agents/product_analysis.py`：确定性 `AgentProtocol` 专家（无 LLM/ReAct），
  写回 `FactSnapshot(domain="product")`。
- 产品库：`query_by_codes`（批量）、`search_by_name`（返回**全部**候选，无 `LIMIT 1`）、
  `recommended_holding_period` 字段，以及逐区块 `source`/`as_of`/`freshness`。
- 槽位层：独立 `product_codes` 槽位（产品代码不等同股票代码）、`product_names`，以及
  产品的 `risk_preference`/`holding_period` 画像回填。
- 配置：`PRODUCT_PERFORMANCE_FRESHNESS_DAYS`、`PRODUCT_HOLDINGS_FRESHNESS_DAYS`。

## main 分支上合并时修复的缺陷（原分支同样存在）

1. **崩溃被报成 SUCCESS**：流水线异常写 `status="failed"`，而编排层只识别 `degraded`，
   其余一律 `SUCCESS`。已改为显式状态映射（含 `failed`/`error`/`timeout`/`blocked`/`cancelled`）。
2. **产品请求不回填画像**：产品适配判断对本轮请求永远不可用。已在产品槽位加入
   `risk_preference`/`holding_period` 并回填缺失画像（不覆盖已确认值）。
3. **产品名抽取脆弱**：请求短语被贪婪正则整串当作产品名（"帮我看看华夏成长基金"），
   且只剩类型词的空壳（"推荐几只基金"）也算命中。已加噪声剥离与空壳剔除。
4. **异常原文外泄**：失败报告直接拼接异常文本（可能含连接串）。已改为固定文案 + 日志记详情。

## 验证证据

- `python -m pytest -q`：**327 passed, 17 skipped**。
  新增 `tests/test_product_defects.py`（9 项，逐条锁定上述缺陷），
  移植 `tests/test_product_research.py`（11）、`tests/test_product_analysis_agent.py`（3）、
  `tests/test_product_library.py`（3）。
- 产品端到端（离线）：代码/名称解析、歧义不猜、陈旧数据只披露、画像匹配/不匹配、
  缺数据即"暂无"。

## 遗留（不在本次）

- **文档 RAG 链路**仍留在分支 `codex/product-rag-document-workspace`，且**未完成**：
  缺组合根（MinIO/Milvus/embedder 装配）、Celery 三个队列、`PostgresDocumentRepository`
  被 ingestion 调用的 4 个方法、schema 初始化未执行 `007`、Milvus collection/sparse 向量、
  admin API 与前端工作台，以及接入 `product_analysis` 的引用增强。定位保持"只追加可追溯
  原文引用、故障降级"，**不改变"事实只来自产品库"**这条不变量。
- 产品数据需由运维灌库（见 `tools/generate_product_seed.py` 与 `sql/007_product_seed.sql`）。
