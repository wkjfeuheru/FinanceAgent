# 监督者意图驱动工作流设计

## 目标

后续工作流只能依据监督者 Agent 已识别并校验的结构化意图计划执行，不得再次扫描用户原文或子请求中的关键词来推断应运行的业务节点。

本次修改覆盖意图兜底、槽位提取候选、市场概览搜索、主题候选搜索、个股解析和资产配置续接。公开 API、四类业务意图和现有 LangGraph 节点保持不变。

## 设计原则

- 监督者是本轮业务编排的唯一决策入口。
- 分类与执行计划在同一次监督者推理中产生，避免后续节点重新解释自然语言。
- 后续节点只消费经过校验的枚举字段，不读取文本决定路由。
- 主模型失败时使用多语言 NLI；NLI 也失败时生成安全的 `casual_chat` 计划。
- 不使用关键词、正则表达式或股票名称词表作为工作流选择兜底。
- 股票代码和名称解析仍可由槽位工具完成；“解析实体”不等于“决定工作流”。

## 监督者输出协议

每个意图项在现有 `intent`、`query`、`confidence` 和 `reason` 基础上增加：

```json
{
  "intent": "market_query | stock_recommendation | asset_allocation | casual_chat",
  "query": "该工作流负责的独立子请求",
  "confidence": 0.0,
  "reason": "简短原因",
  "execution_mode": "security_analysis | market_overview | candidate_search | security_comparison | allocation | conversation",
  "requires_slot_extraction": false
}
```

合法组合如下：

| 意图 | execution_mode | 槽位规则 | 后续工作流 |
| --- | --- | --- | --- |
| `market_query` | `security_analysis` | `true` | 槽位解析 → 个股数据 → 基本面 |
| `market_query` | `market_overview` | `false` | 市场网页搜索，不解析个股 |
| `stock_recommendation` | `candidate_search` | `false` | 网页候选搜索 → 个股数据 → 基本面 |
| `stock_recommendation` | `security_comparison` | `true` | 槽位解析 → 个股数据 → 基本面比较 |
| `asset_allocation` | `allocation` | `true` | 槽位解析 → 配置状态检查 → 资产配置 |
| `casual_chat` | `conversation` | `false` | 闲聊 → 合规 |

非法组合由监督者结果校验器规范化为对应意图的安全默认值，不允许后续节点依据 query 猜测。例如，无法确定 `stock_recommendation` 的子类型时使用 `candidate_search`；无法确定 `market_query` 的子类型时不发起个股工具调用，并返回可解释的缺少执行策略错误，而不是关键词推断。

## 分类与降级链路

正常路径由监督者轻量模型输出完整结构化计划。结果校验器负责：

1. 拒绝未知意图和未知执行模式。
2. 合并重复意图，并保留每类意图一个独立 query。
3. 强制执行合法的意图、模式和槽位布尔值组合。
4. 生成 `task_plan`，但不预先加入实际尚未执行的 `slot_extraction`。

失败路径为：

```text
监督者主模型失败或返回不可用结果
  → 多语言 NLI 分类器
  → NLI 依据标签映射生成保守执行计划
  → NLI 也失败时生成 casual_chat / conversation
```

NLI 只能确定四类意图，不能稳定区分同一意图内部的执行模式。因此其保守映射为：

- `market_query`：不自动调用槽位或网页搜索，返回缺少明确执行策略的可恢复错误。
- `stock_recommendation`：使用 `candidate_search`，不调用槽位工具。
- `asset_allocation`：使用 `allocation`，必须调用槽位工具。
- `casual_chat`：使用 `conversation`。

原 `_rule_intents()`、`_finance_related()` 关键词兜底及资产配置关键词强制补齐逻辑删除。`finance_related` 由监督者结果提供；双重失败时固定为 `false`。

## LangGraph 路由

`supervisor_handler` 将标准化后的意图计划写入 `detected_intents`。现有图结构保留：

```text
supervisor
  → slot_tool_decision
  → slot_tool_executor（存在有效调用时）
  → business_state_guard
  → stock_resolution
  → 各业务节点
```

节点行为调整如下：

- `route_after_supervisor` 只查看意图枚举。
- `_slot_candidate_intents` 只查看 `requires_slot_extraction`，不调用文本判断函数。
- 槽位 Tool Call 模型只能在监督者批准的候选中选择；资产配置漏调时可按结构化计划确定性补调。
- `stock_resolution_handler` 根据 `execution_mode` 选择市场概览搜索、候选搜索或个股解析。
- `route_after_slots`、`route_after_data_fetch` 等路由只查看意图计划、结构化状态和执行结果。
- 等待中的资产配置由监督者通过上下文识别为 `asset_allocation/allocation`；取消请求同样由监督者产生 `casual_chat/conversation`，不在编排器中匹配“取消”等词。

## 状态与兼容性

不增加顶层公开状态字段。`detected_intents` 中新增的两个字段随现有内部结果返回，但前端无需读取。

为兼容旧检查点，缺少新字段的历史意图项在恢复时进行安全规范化：

- `asset_allocation` → `allocation`、需要槽位。
- `casual_chat` → `conversation`、不需要槽位。
- 其他缺少模式的业务意图不通过文本补推断，进入可恢复错误路径。

`task_plan` 仍记录实际执行节点；只有槽位工具真正运行后才插入 `slot_extraction`。

## 错误处理

- 主模型结果非法：尝试 NLI，不调用关键词兜底。
- NLI 不可用：安全降级为非金融闲聊响应。
- 执行模式非法或缺失：记录对应意图错误，其他意图继续执行。
- Tool Call 非法、重复或越权：沿用现有校验并拒绝，仅对结构化计划明确要求的漏调执行确定性补调。
- 某个意图执行失败：隔离到 `intent_results[intent]`，不阻断其他意图。

## 删除范围

删除所有用于决定后续工作流的文本启发式函数及调用，包括：

- `_INVESTMENT_ADVICE_MARKERS`
- `needs_investment_profile()`
- `needs_asset_allocation()`
- `_rule_intents()`
- `_finance_related()`
- `needs_stock_screening()`
- `needs_market_overview_search()`
- `needs_slot_extraction()` 中基于 query 的判断

若某个辅助函数仅用于实体格式校验、工具参数校验或展示，不参与选择工作流，可以保留，但必须由测试证明它不会改变路由。

## 测试策略

采用 TDD，先写失败测试再修改实现。

1. 监督者协议测试
   - 校验所有合法意图与执行模式组合。
   - 拒绝或安全规范化非法组合。
   - 同义改写和不含旧关键词的表达仍由模型结构化计划正确路由。

2. 无关键词路由测试
   - monkeypatch 旧文本判断函数为抛错，工作流仍能按结构化计划完成。
   - `market_overview` 只调用市场搜索。
   - `candidate_search` 只调用候选搜索。
   - `security_analysis` 与 `security_comparison` 才允许个股槽位调用。
   - `allocation` 始终允许槽位调用。

3. 降级测试
   - 主模型失败后调用 NLI。
   - 主模型和 NLI 均失败时只产生 `casual_chat/conversation`。
   - 双重失败不读取消息关键词，即使输入包含“推荐”“配置”也不启动业务工作流。

4. 多意图与回归测试
   - 行情、推荐、配置、闲聊组合分别执行各自模式。
   - 每个意图的股票集合保持隔离，相同行情数据仍去重获取。
   - 推荐候选继续可传递给资产配置。
   - 完整后端测试和前端构建通过。

## 非目标

- 不更换现有意图标签或 LangGraph 框架。
- 不修改槽位提取工具的公开参数和返回结构。
- 不重做金融数据源、搜索服务或前端展示。
- 不用另一个独立路由模型增加额外请求；执行策略由监督者分类请求一次生成。
