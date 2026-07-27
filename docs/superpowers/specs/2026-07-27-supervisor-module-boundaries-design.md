# 监督者与槽位工具模块边界设计

## 目标

将意图识别实现收拢到监督者模块，将槽位解析与原生 Tool Calling 完整迁入工具目录，使代码位置与运行时职责一致：监督者负责识别和编排，工具负责按调用提取结构化金融槽位。

本次调整是内部模块重构。现有 LangGraph 节点、状态字段、HTTP API、四类业务意图和 `extract_finance_slots` 工具协议保持不变。

## 模块结构

调整后的核心结构为：

```text
finance_agent/
  agents/
    supervisor.py
      - NLI 标签与分句规则
      - ZeroShotIntentClassifier
      - 结构化执行计划校验
      - SupervisorAgent
  tools/
    finance_slots.py
      - FinanceSlotsExtractor
      - 槽位 Prompt 与解析实现
      - extract_investment_goal
      - create_extract_finance_slots_tool
```

删除：

- `finance_agent/intent_classifier.py`
- `finance_agent/agents/profile_extraction.py`
- `SlotExtractionAgent`
- `ProfileExtractionAgent`

不保留旧模块或旧类名的兼容转发。项目内所有调用者和测试一次性迁移到新边界。

## 意图识别

### 固定首选模型

每轮意图识别首先且唯一使用：

```text
MoritzLaurer/mDeBERTa-v3-base-mnli-xnli
```

模型名称作为 `agents/supervisor.py` 内部常量固定，不允许通过环境变量切换。`SupervisorAgent.classify_intents()` 直接调用内置的 `ZeroShotIntentClassifier`。

### 删除的路径

删除所有聊天模型分类与影子比较逻辑：

- `_intent_chain`
- 监督者 LLM 分类 Prompt
- `_SHADOW_EXECUTOR`
- `_submit_shadow_prediction()`
- `INTENT_CLASSIFIER_MODE`
- `INTENT_MODEL`
- `INTENT_MODEL_TIMEOUT`
- `INTENT_MODEL_MAX_RETRIES`
- `INTENT_ZERO_SHOT_MODEL`
- `get_intent_model()`

不得使用聊天模型或关键词规则补充分类型意图。

### 保留的运行配置

以下配置直接控制固定 NLI 推理，继续保留：

- `INTENT_MODEL_CACHE_DIR`
- `INTENT_MAX_LENGTH`
- `INTENT_SCORE_THRESHOLD`
- `INTENT_DEVICE`

### 分类结果与失败策略

NLI 返回现有 `intents`、`finance_related` 和 `latency_ms` 结构。监督者继续把标签映射为结构化执行模式：

- `market_query` → `unsupported`
- `stock_recommendation` → `candidate_search`
- `asset_allocation` → `allocation`
- `casual_chat` → `conversation`

`market_query` 的 NLI 结果无法安全区分个股与市场概览，因此保持 `unsupported`，不扫描 query 推断。

模型加载、推理、输出校验或低置信度过滤后没有有效意图时，固定生成：

```json
{
  "intent": "casual_chat",
  "execution_mode": "conversation",
  "requires_slot_extraction": false,
  "confidence": 0.0,
  "reason": "意图分类服务暂不可用"
}
```

`intent_source` 正常为 `zero_shot`，安全降级为 `safe_fallback`。不再出现 `model`、`shadow`、`model+rule` 或 `zero_shot+rule`。

## 监督者聊天模型

槽位 Tool Calling 决策和理财闲聊生成仍属于监督者能力，但不属于意图识别。

配置层提供明确命名的 `get_supervisor_model()`：

- 固定使用 `deepseek:deepseek-v4-flash`
- 复用 `LLM_REQUEST_TIMEOUT` 和 `LLM_MAX_RETRIES`
- 不新增任何 `INTENT_*` 聊天模型配置

`decide_slot_tool_calls()` 与 `chat()` 使用该入口。它们不得参与 `classify_intents()`。

## 槽位工具

### FinanceSlotsExtractor

`FinanceSlotsExtractor` 是无 LangGraph 节点身份的工具运行时依赖，不继承 `BaseFinanceAgent`，不提供面向用户的 `handle()`。

它负责：

- 正则提取风险偏好、预算、期限、目标和显式股票代码
- 必要时调用槽位 LLM 补全语义字段
- 合并本轮槽位与已有长期画像
- 输出 `user_profile`、`resolved_stocks` 和 `explicit_stock_codes`

其主要接口为：

```python
class FinanceSlotsExtractor:
    def extract_profile(
        self,
        message: str,
        existing_profile: dict | None = None,
        conversation_context: str = "",
    ) -> dict: ...

    def extract_slots(
        self,
        message: str,
        existing_profile: dict | None = None,
        conversation_context: str = "",
    ) -> dict: ...
```

### 原生工具工厂

`create_extract_finance_slots_tool()` 与提取器放在同一模块，继续对模型公开：

```json
{
  "intent": "market_query | stock_recommendation | asset_allocation",
  "query": "该意图的独立子请求"
}
```

已有画像和对话上下文仍由工具执行节点注入，不暴露给模型。工具返回结构不变。

### 编排器命名

`AdvisorSystem` 中：

- `self.slot_agent` 改为 `self.finance_slots_extractor`
- 工具工厂从 `finance_agent.tools.finance_slots` 导入
- 进度阶段 `slot_extraction`、状态字段 `slot_tool_*` 和 Agent trace 名称 `SlotExtractionTool` 保持不变，以兼容前端和诊断数据

## 导出边界

`finance_agent/agents/__init__.py` 不再导出任何槽位 Agent。

`finance_agent/tools/__init__.py` 导出：

- `FinanceSlotsExtractor`
- `create_extract_finance_slots_tool`
- `extract_investment_goal`

生产代码和测试不得从已删除模块导入。

## 错误处理

- 固定 NLI 不可用：安全降级闲聊，不尝试聊天模型分类。
- 槽位正则已得到充分结果：沿用快速返回，避免无意义 LLM 调用。
- 槽位 LLM 失败：保留正则结果，不中断其他意图。
- 某个 Tool Call 失败：沿用按意图隔离错误，不阻断其他调用。
- 删除旧模块后出现导入错误：视为迁移缺陷，不通过兼容 shim 掩盖。

## 测试策略

采用 TDD，迁移前先修改导入和行为测试并观察失败。

1. 固定 NLI 测试
   - 从 `finance_agent.agents.supervisor` 导入分类器。
   - 断言默认加载模型严格为 `MoritzLaurer/mDeBERTa-v3-base-mnli-xnli`。
   - 断言 `classify_intents()` 首次调用 NLI，且不会构造聊天分类链。
   - 断言 NLI 异常或空结果进入 `safe_fallback`。

2. 配置删除测试
   - 更新配置子进程测试，确认已删除的环境变量不再影响行为。
   - 保留缓存目录、最大长度、阈值和设备配置测试。
   - 验证 `get_supervisor_model()` 独立于意图识别。

3. 槽位工具迁移测试
   - 从 `finance_agent.tools.finance_slots` 导入提取器和工具工厂。
   - 复用投资目标、预算、风险、期限和股票隔离测试。
   - 验证标准 `tool_calls` 的参数和返回协议保持不变。

4. 边界审计
   - 旧两个 Python 文件不存在。
   - 生产代码没有 `intent_classifier`、`profile_extraction`、`SlotExtractionAgent`、`ProfileExtractionAgent` 或 `slot_agent` 引用。
   - 不用单元测试锁定源码文本；以导入、运行行为和最终审计共同验证。

5. 回归
   - 后端全量测试通过。
   - 前端生产构建通过。
   - 多意图、Tool Calling、等待配置、股票集合隔离和安全降级保持通过。

## 非目标

- 不调整 NLI 标签文案、阈值语义或多意图分句算法。
- 不改变监督者结构化执行计划协议。
- 不改变槽位工具公开名称、参数或返回结构。
- 不修改前端显示、外部 API、金融数据源或资产配置算法。
