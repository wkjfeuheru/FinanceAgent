# 闲聊专家（CasualChatAgent）详细设计

## 1. 概述

| 属性 | 值 |
|------|-----|
| 模块路径 | `finance_agent/agents/casual_chat.py`（新增） |
| 基类 | `ProceduralAgent`（过程式，单次 LLM 调用） |
| agent_name | `casual_chat` |
| 温度 | `0.0`（使用 `get_supervisor_model` 轻量模型 `deepseek-v4-flash`） |
| 模型 | `deepseek:deepseek-v4-flash` |
| 超时 | `LLM_REQUEST_TIMEOUT`（默认 45s） |

### 职责

- 接收总管路由的闲聊需求（`casual_chat` 意图）
- 生成自然、有同理心的闲聊回复
- 保留金融边界约束：闲聊偏离金融主题时温和引导回投资理财话题
- **不调用**任何金融数据工具，不查询行情、不推荐证券、不生成配置方案
- 将回复写入 `AdvisorState.intent_results["casual_chat"]`

---

## 2. 内部工作流

```
用户消息 + requirement + AdvisorState 上下文
          │
          ▼
   ┌──────────────────────┐
   │  1. 金融相关性判断    │  检查 finance_related 标志
   │  （来自总管意图识别）  │  - true: 金融相关闲聊
   │                      │  - false: 非金融话题
   └──────────┬───────────┘
              │
              ▼
   ┌──────────────────────┐
   │  2a. 金融相关闲聊     │  调用 LLM 生成闲聊回复
   │  （LLM 生成）         │  可讨论投资情绪、经验、心态、一般金融知识
   │                      │  不查询行情、不推荐证券、不生成配置
   └──────────┬───────────┘
              │
              ▼
   ┌──────────────────────┐
   │  2b. 非金融话题引导   │  返回固定引导语（不调用 LLM）：
   │  （固定回复）         │  "我主要协助处理投资理财、证券行情、
   │                      │   选股研究和资产配置问题。
   │                      │   你可以从这些方面继续问我。"
   └──────────┬───────────┘
              │
              ▼
   写入 AdvisorState.intent_results["casual_chat"]
   = {"status": "success", "content": response}
```

---

## 3. 提示词模板

### 3.1 System Prompt（金融相关闲聊）

```
你是有同理心且审慎的理财交流助手。只回应给定的闲聊子请求，可以讨论投资情绪、经验、心态和一般金融知识；不要查询或编造行情数据，不要推荐具体证券，不要生成个人资产配置方案。回答简洁自然。
```

### 3.2 Human 模板

```
近期对话：
{context}

闲聊子请求：{query}
```

### 3.3 非金融话题引导语（固定文本，非 LLM）

```
我主要协助处理投资理财、证券行情、选股研究和资产配置问题。你可以从这些方面继续问我。
```

---

## 4. JSON Schema 数据流

### 4.1 输入（从 AdvisorState 读取）

```json
{
  "user_message": "最近市场波动好大，有点慌",
  "requirement": "最近市场波动好大，有点慌",
  "finance_related": true,
  "chat_history": [
    {"role": "user", "content": "帮我分析贵州茅台"},
    {"role": "assistant", "content": "## 股票分析报告\n..."}
  ],
  "memory_context": "用户此前询问了贵州茅台分析..."
}
```

### 4.2 输出（写入 AdvisorState）

```json
{
  "intent_results": {
    "casual_chat": {
      "status": "success",
      "content": "市场波动确实是投资中常见的挑战。短期波动往往受情绪和资金面影响，关键在于持有的标的是否有坚实的基本面支撑。如果之前分析的标的基本面依然稳健，短期波动反而可能是布局机会。建议关注长期价值而非短期价格波动。"
    }
  },
  "agent_response": "市场波动确实是投资中常见的挑战..."
}
```

---

## 5. Tools 清单

闲聊专家**不持有任何工具**，不调用金融数据接口。纯 LLM 文本生成（金融相关）或固定引导语（非金融）。

---

## 6. 错误处理与降级

| 场景 | 处理 |
|------|------|
| LLM 调用超时 | 返回"暂时无法回应这部分交流内容，请稍后重试" |
| LLM 调用异常 | 返回"暂时无法回应这部分交流内容：{error}" |
| 非金融话题 | 直接返回固定引导语，不调用 LLM，零延迟 |

---

## 7. 设计说明

### 7.1 从总管拆出的理由

原 `SupervisorAgent.chat()` 方法同时承担意图识别和闲聊生成两个职责，违背单一职责原则。拆出独立 `CasualChatAgent` 后：
- 总管专注意图识别 + 路由 + 合成
- 闲聊专家专注闲聊生成
- 闲聊可以使用更轻量的模型（`deepseek-v4-flash`），降低成本

### 7.2 金融边界约束

闲聊专家保留金融边界约束：
- `finance_related=true`：用户在金融范围内闲聊（如投资心态、市场感受），正常回应
- `finance_related=false`：用户完全偏离金融话题（如天气、 sports），温和引导回金融主题

### 7.3 模型选择

使用 `get_supervisor_model()`（`deepseek-v4-flash`，温度 0）而非 `get_model_for_agent("casual_chat")`，因为：
- 闲聊不需要深度推理，flash 模型足够
- 降低 token 成本与延迟
- 温度 0 保证回复一致性
