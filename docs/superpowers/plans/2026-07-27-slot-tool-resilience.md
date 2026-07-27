# 槽位工具容错修复实施计划

> **供代理执行者使用：** 必须使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans，逐任务执行本计划。步骤使用复选框（`- [ ]`）跟踪。

**目标：** 在不改变现有图拓扑和公开 API 的前提下，使槽位 Tool Call 能安全处理异常模型调用、异常工具结果，并收紧非个股行情的确定性调用边界。

**架构：** 保留 `slot_tool_decision` 与 `slot_tool_executor` 两节点。决策节点把模型输出视为不可信数据，执行节点把每个意图的调用、规范化和合并放在同一异常边界内；`needs_slot_extraction()` 只负责确定明确需要槽位的候选意图。

**技术栈：** Python 3.10+、LangGraph、LangChain 原生 Tool Calling、pytest、Vue/Vite。

## 全局约束

- 不改变 `extract_finance_slots(intent, query)` 的公开工具参数。
- 不改变前后端公开 API、LangGraph 节点名称或状态字段名称。
- 一个意图失败不得阻止其他意图执行。
- 只有成功验证的结果才能更新画像和股票状态。
- 不运行需要网络或真实 API 的 smoke test，除非环境已准备且用户明确授权。

---

### Task 1：收紧确定性候选边界并删除重复定义

**文件：**
- 修改：`finance_agent/agents/supervisor.py:156-177`
- 测试：`tests/test_slot_tool_routing.py`

**接口：**
- 输入：`needs_slot_extraction(intent: str, query: str) -> bool`
- 输出：资产配置恒为 `True`；明确个股行情/比较为 `True`；板块、指数、商品、汇率和泛化主题为 `False`。

- [ ] **Step 1：添加失败测试**

```python
def test_slot_tool_skips_non_stock_market_requests():
    assert not needs_slot_extraction("market_query", "黄金价格最近走势")
    assert not needs_slot_extraction("market_query", "美元汇率今天怎么样")


def test_slot_tool_accepts_explicit_stock_references():
    assert needs_slot_extraction("market_query", "分析600519基本面")
    assert needs_slot_extraction("market_query", "贵州茅台最近走势")
    assert needs_slot_extraction("stock_recommendation", "茅台和五粮液哪个更值得买")
```

- [ ] **Step 2：验证 RED**

运行：`.\.venv\Scripts\python.exe -m pytest tests/test_slot_tool_routing.py -v`

预期：非个股行情测试失败，因为当前实现对其返回 `True`。

- [ ] **Step 3：最小实现**

删除重复函数，只保留一个定义。用股票代码正则、常见明确股票名称/简称以及“个股/这只股票/该股”等指代判断股票请求；资产配置仍恒为 `True`，板块、行业、概念、指数、商品和汇率优先排除。

- [ ] **Step 4：验证 GREEN**

运行：`.\.venv\Scripts\python.exe -m pytest tests/test_slot_tool_routing.py -v`

预期：全部通过。

- [ ] **Step 5：提交**

```powershell
git add finance_agent/agents/supervisor.py tests/test_slot_tool_routing.py
git commit -m "fix: tighten slot tool routing boundaries"
```

### Task 2：防御异常 Tool Call 并保持确定性兜底

**文件：**
- 修改：`finance_agent/core/orchestrator.py:465-499`
- 测试：`tests/test_multi_intent_workflow.py`

**接口：**
- 输入：`SupervisorAgent.decide_slot_tool_calls(...) -> list[Any]`
- 输出：`state["slot_tool_calls"]` 只包含已验证、按意图去重的字典；异常条目被忽略，缺失候选由确定性兜底补齐。

- [ ] **Step 1：添加失败测试**

增加图级测试，让 `decide_slot_tool_calls` 返回：

```python
[
    None,
    "bad-call",
    {"name": "extract_finance_slots", "args": "bad-args"},
]
```

分类结果只包含 `asset_allocation`，断言工作流没有抛错、`slot_tool_source == "deterministic_fallback"`，并且工具最终调用一次。

- [ ] **Step 2：验证 RED**

运行：`.\.venv\Scripts\python.exe -m pytest tests/test_multi_intent_workflow.py -v`

预期：失败于 `call.get` 或 `args.get`。

- [ ] **Step 3：最小实现**

在访问字段前增加：

```python
if not isinstance(call, dict):
    continue
args = call.get("args")
if not isinstance(args, dict):
    continue
```

保留现有工具名、候选意图、精确 query 和重复意图校验；模型漏掉的候选继续由现有确定性逻辑补齐。

- [ ] **Step 4：验证 GREEN**

运行：`.\.venv\Scripts\python.exe -m pytest tests/test_multi_intent_workflow.py -v`

预期：全部通过。

- [ ] **Step 5：提交**

```powershell
git add finance_agent/core/orchestrator.py tests/test_multi_intent_workflow.py
git commit -m "fix: validate slot tool decisions defensively"
```

### Task 3：隔离异常工具结果并完成回归验证

**文件：**
- 修改：`finance_agent/core/orchestrator.py:505-566`
- 测试：`tests/test_multi_intent_workflow.py`

**接口：**
- 输入：每个 `extract_finance_slots` 调用结果。
- 输出：有效结果增量合并；无效结果只追加 `<intent>: <error>` 到 `slot_tool_error`，后续意图继续执行。

- [ ] **Step 1：添加失败测试**

增加双意图图级测试：`market_query` 工具返回 `None` 或含非字典股票项的结果，`asset_allocation` 返回有效预算画像。断言：

```python
assert result["user_profile"]["budget_amount"] == 100000
assert "market_query" in result["slot_tool_error"]
assert result["slot_tool_called"] is True
```

- [ ] **Step 2：验证 RED**

运行：`.\.venv\Scripts\python.exe -m pytest tests/test_multi_intent_workflow.py -v`

预期：异常结果在 `result.get` 或股票合并阶段中断整个工作流。

- [ ] **Step 3：最小实现**

把结果类型校验、`user_profile`/`resolved_stocks`/`explicit_stock_codes` 类型校验、股票项规范化和状态合并放入当前调用的 `try`。遇到无效结构抛出 `ValueError`，由该调用的 `except` 记录错误并继续循环。仅成功调用更新状态。

- [ ] **Step 4：运行聚焦测试**

运行：`.\.venv\Scripts\python.exe -m pytest tests/test_slot_tool_routing.py tests/test_multi_intent_workflow.py -v`

预期：全部通过。

- [ ] **Step 5：运行完整验证**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q finance_agent tests
Set-Location frontend
npm run build
```

预期：后端测试、语法检查和前端构建均成功；允许保留既有 Vite chunk-size 警告。

- [ ] **Step 6：提交**

```powershell
git add finance_agent/core/orchestrator.py tests/test_multi_intent_workflow.py
git commit -m "fix: isolate slot tool result failures"
```
