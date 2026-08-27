## Purpose

定义资产配置辩论能力：在资产配置专家内部，由"看多"分析师根据约束条件提出配置方案，"看空"分析师针对方案进行质疑与风险识别，多轮对抗后由资产配置专家仲裁双方观点，产出最终配置决策。

## ADDED Requirements

### Requirement: 资产配置专家编排看多/看空辩论驱动决策

资产配置专家 SHALL 在获取各标的历史数据与参考指标后，当 `DEBATE_ENABLED=true` 且标的数 >= 2 时，编排辩论驱动决策流程：先由看多分析师根据约束条件（风险偏好、预算、年限、最大回撤容忍度）提出配置方案（含权重与成长逻辑），再由看空分析师针对方案逐项质疑（含风险清单与调整建议），多轮对抗后由资产配置专家仲裁产出最终配置权重。当 `DEBATE_ENABLED=false` 时跳过辩论，由资产配置专家直接根据参考指标与基本面生成配置方案并标注"辩论未执行"。

#### Scenario: 看多方提出方案后看空方质疑

- **WHEN** 资产配置专家获取历史数据与参考指标后启动辩论
- **THEN** 看多分析师根据约束条件提出配置方案（含各标的权重与成长逻辑），看空分析师针对方案逐项质疑（估值/集中度/回撤/宏观风险），辩论输入包含各标的年化收益、波动率、夏普比率与 `AdvisorState` 中的基本面分析

#### Scenario: 辩论被禁用时跳过

- **WHEN** `DEBATE_ENABLED=false`
- **THEN** 资产配置专家跳过辩论，直接根据参考指标与基本面生成配置方案并标注"辩论未执行"

### Requirement: 看多与看空分析师进行多轮对抗辩论

辩论协调器 SHALL 使用 AutoGen GroupChat 编排"看多分析师"与"看空分析师"进行最多 `DEBATE_MAX_ROUNDS`（默认 2）轮对抗辩论：看多分析师先根据约束条件提出配置方案（含权重与成长逻辑），看空分析师随后针对方案逐项质疑并提出风险清单与调整建议。后续轮次中看多方回应质疑，看空方继续追问未解决风险。所有 LLM 调用 MUST 使用 DeepSeek（复用 `DEEPSEEK_API_KEY`），不得引入其他 LLM 厂商。

#### Scenario: 默认 2 轮辩论

- **WHEN** 辩论启动且 `DEBATE_MAX_ROUNDS=2`
- **THEN** 看多分析师提出方案后，看空分析师质疑，看多方回应，看空方追问，共 4 次发言后进入仲裁

#### Scenario: 轮次上限强制收敛

- **WHEN** 辩论达到 `DEBATE_MAX_ROUNDS` 轮
- **THEN** 协调器停止发言并进入结论聚合，不产生超出轮次的发言

### Requirement: 辩论结论结构化回传并由主 Agent 仲裁

辩论协调器 SHALL 返回结构化 `DebateResult`，包含看多方配置方案（`bull_plan`）、看空方质疑清单（`bear_challenges`）、未解决风险（`unresolved_risks`）、双方核心论据与分歧/共识点；资产配置专家 SHALL 综合看多方方案与看空方质疑进行仲裁，产出最终配置权重与仲裁理由，将辩论摘要写入 `allocation_result["debate"]` 并在报告中生成"辩论摘要"小节。

#### Scenario: 仲裁后写入配置报告

- **WHEN** 辩论完成并返回 `DebateResult`
- **THEN** 资产配置专家仲裁双方观点产出最终权重，将结论写入 `allocation_result["debate"]`，报告中新增"辩论摘要"小节展示双方论据、仲裁理由与分歧/共识

### Requirement: 仲裁时对未解决风险显式标注

当辩论 `unresolved_risks` 中存在未被看多方有效反驳的重大风险时，资产配置专家 SHALL 在仲裁中对该标的降低权重或标注风险提示，并记录"辩论提示风险"；冲突处理 MUST 保守倾向（降权或提示），不得自动大幅反向调仓。

#### Scenario: 看空方指出重大风险时仲裁降权

- **WHEN** 看空分析师指出某标的估值严重偏高且看多分析师未能有效反驳
- **THEN** 资产配置专家在仲裁中降低该标的权重，在仲裁理由中标注"看空方质疑合理，降低权重"，并记录未解决风险

### Requirement: 辩论超时降级

当辩论总耗时超过 `DEBATE_TIMEOUT`（默认 60s）时，协调器 SHALL 终止辩论并返回 `DebateResult(status="timeout")`；资产配置专家 SHALL 跳过辩论结论，基于 MPT 结果生成报告并标注"辩论超时未完成"。

#### Scenario: 辩论超时后降级

- **WHEN** 辩论总耗时超过 60 秒
- **THEN** 协调器返回超时状态，资产配置专家报告中标注"辩论超时未完成"，不因超时阻塞主流程

### Requirement: 辩论结论通过 allocation_result.debate 对外暴露

`allocation_result` 新增可选 `debate` 子字段，结构为 `{bull_arguments, bear_arguments, disagreements, convergences}`；`api/schemas.py` 响应体 SHALL 声明该字段为可选；前端缺失该字段时 MUST NOT 报错。

#### Scenario: 前端可选展示辩论摘要

- **WHEN** 前端 `AllocationChart.vue` 读取 `allocation_result.debate` 字段
- **THEN** 字段存在时展示辩论摘要；字段缺失时正常展示配置结果不报错
