# Supervisor Module Boundaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将固定 mDeBERTa 意图识别并入监督者，并将槽位解析与原生 Tool Calling 完整迁入工具目录。

**Architecture:** `agents/supervisor.py` 内聚 NLI 分类器、执行计划校验和监督者行为；`tools/finance_slots.py` 提供无 Agent 身份的槽位提取器与工具工厂。删除旧模块、旧类名、聊天模型分类和影子模式，保持 LangGraph 状态与公开 Tool Call 协议不变。

**Tech Stack:** Python 3.11、Transformers zero-shot pipeline、LangChain tools、LangGraph、pytest

## Global Constraints

- 意图识别首先且唯一使用 `MoritzLaurer/mDeBERTa-v3-base-mnli-xnli`。
- 意图识别不得调用聊天模型或关键词兜底；NLI 不可用时进入 `safe_fallback`。
- 删除 `finance_agent/intent_classifier.py` 与 `finance_agent/agents/profile_extraction.py`，不保留兼容 shim。
- 槽位实现使用 `FinanceSlotsExtractor`，不继承 `BaseFinanceAgent`，不提供 `handle()`。
- `extract_finance_slots` 的工具名称、参数与返回结构不变。
- 不改变 LangGraph 节点、状态字段、HTTP API 或前端协议。
- 每项生产改动必须先写测试并观察预期失败。
- 不提交数据库、缓存、模型、`data/` 或无关 `.superdesign` 删除。

---

## 文件结构

- Modify: `finance_agent/agents/supervisor.py` — 内置固定 NLI 分类器并删除 LLM 分类路径。
- Create: `finance_agent/tools/finance_slots.py` — 槽位提取与 Tool Calling 工具。
- Modify: `finance_agent/core/orchestrator.py` — 使用 `FinanceSlotsExtractor`。
- Modify: `finance_agent/config.py` — 删除无关意图配置，提供监督者轻量模型入口。
- Modify: `finance_agent/agents/__init__.py` — 删除槽位 Agent 导出。
- Modify: `finance_agent/tools/__init__.py` — 导出槽位工具接口。
- Delete: `finance_agent/intent_classifier.py`
- Delete: `finance_agent/agents/profile_extraction.py`
- Modify: `tests/test_zero_shot_intent_classifier.py`
- Modify: `tests/test_supervisor_multi_intent.py`
- Modify: `tests/test_intent_config.py`
- Modify: `tests/test_profile_investment_goal.py`
- Modify: `tests/test_multi_intent_workflow.py`

### Task 1: 将固定 NLI 分类器并入监督者

**Files:**
- Modify: `finance_agent/agents/supervisor.py`
- Delete: `finance_agent/intent_classifier.py`
- Modify: `tests/test_zero_shot_intent_classifier.py`
- Modify: `tests/test_supervisor_multi_intent.py`

**Interfaces:**
- Produces: `SupervisorAgent.zero_shot_classifier -> ZeroShotIntentClassifier`
- Produces: `ZeroShotIntentClassifier.predict(message, context="", pending_allocation=False) -> dict`
- Produces: `split_intent_queries(message: str) -> list[str]`
- Uses fixed model: `MoritzLaurer/mDeBERTa-v3-base-mnli-xnli`

- [ ] **Step 1: 修改分类器导入并写固定模型行为测试**

把 `tests/test_zero_shot_intent_classifier.py` 的导入改为：

```python
from finance_agent.agents.supervisor import (
    ZeroShotIntentClassifier,
    split_intent_queries,
)
```

在 `tests/test_supervisor_multi_intent.py` 新增：

```python
def test_supervisor_builds_fixed_mdeberta_classifier(monkeypatch):
    captured = {}

    class RecordingClassifier:
        def __init__(self, model_name, **kwargs):
            captured["model_name"] = model_name
            captured["kwargs"] = kwargs

    monkeypatch.setattr(supervisor_module, "ZeroShotIntentClassifier", RecordingClassifier)
    agent = object.__new__(SupervisorAgent)
    agent._zero_shot_classifier = None

    _ = agent.zero_shot_classifier

    assert captured["model_name"] == "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `.venv\Scripts\python.exe -m pytest tests/test_zero_shot_intent_classifier.py tests/test_supervisor_multi_intent.py::test_supervisor_builds_fixed_mdeberta_classifier -q`

Expected: FAIL，分类器尚未由 `supervisor.py` 导出，且模型仍来自配置。

- [ ] **Step 3: 迁移分类器实现并固定模型**

把 `intent_classifier.py` 中的标签、候选文案、分句函数和 `ZeroShotIntentClassifier` 移入 `supervisor.py`。定义：

```python
_INTENT_ZERO_SHOT_MODEL = "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"
```

`zero_shot_classifier` 属性必须直接传入该常量，并继续传入缓存目录、最大长度、阈值和设备配置。删除 `from finance_agent.intent_classifier ...`，随后删除旧文件。

- [ ] **Step 4: 运行分类器测试并确认 GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests/test_zero_shot_intent_classifier.py tests/test_supervisor_multi_intent.py::test_supervisor_builds_fixed_mdeberta_classifier -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add finance_agent/agents/supervisor.py finance_agent/intent_classifier.py tests/test_zero_shot_intent_classifier.py tests/test_supervisor_multi_intent.py
git commit -m "refactor: embed intent classifier in supervisor"
```

### Task 2: 删除聊天模型分类与无关配置

**Files:**
- Modify: `finance_agent/agents/supervisor.py`
- Modify: `finance_agent/config.py`
- Modify: `tests/test_supervisor_multi_intent.py`
- Modify: `tests/test_intent_config.py`

**Interfaces:**
- Produces: `get_supervisor_model()`，固定返回 `deepseek:deepseek-v4-flash`
- Consumes: `LLM_REQUEST_TIMEOUT`、`LLM_MAX_RETRIES`
- Produces: `classify_intents()` 仅返回 `intent_source` 为 `zero_shot` 或 `safe_fallback`

- [ ] **Step 1: 写 NLI 唯一路径失败测试**

删除测试中对 `INTENT_CLASSIFIER_MODE` 的 monkeypatch，并新增：

```python
def test_classify_intents_never_uses_chat_model(monkeypatch):
    agent = object.__new__(SupervisorAgent)
    agent._zero_shot_classifier = FakeZeroShotClassifier({
        "intents": [{
            "intent": "asset_allocation",
            "query": "安排资金",
            "confidence": 0.9,
            "reason": "NLI",
        }],
        "finance_related": True,
    })
    monkeypatch.setattr(
        supervisor_module,
        "get_supervisor_model",
        lambda: (_ for _ in ()).throw(AssertionError("不得调用聊天模型分类")),
    )

    result = agent.plan_tasks("安排资金")

    assert result["intent_source"] == "zero_shot"
    assert result["intents"][0]["execution_mode"] == "allocation"
```

更新异常测试，令 NLI 抛错并断言唯一结果为 `safe_fallback`。

- [ ] **Step 2: 修改配置测试并确认 RED**

`tests/test_intent_config.py` 只读取 `INTENT_MODEL_CACHE_DIR`、`INTENT_MAX_LENGTH`、`INTENT_SCORE_THRESHOLD`、`INTENT_DEVICE`，并断言模块没有 `INTENT_CLASSIFIER_MODE`、`INTENT_MODEL`、`INTENT_MODEL_TIMEOUT`、`INTENT_MODEL_MAX_RETRIES`、`INTENT_ZERO_SHOT_MODEL`。

Run: `.venv\Scripts\python.exe -m pytest tests/test_supervisor_multi_intent.py tests/test_intent_config.py -q`

Expected: FAIL，旧配置与聊天分类路径仍存在。

- [ ] **Step 3: 删除旧路径并实现监督者模型入口**

从 `config.py` 删除所有列明的旧配置和 `get_intent_model()`，实现：

```python
def get_supervisor_model():
    return init_chat_model(
        "deepseek:deepseek-v4-flash",
        api_key=DEEPSEEK_API_KEY,
        temperature=0,
        timeout=LLM_REQUEST_TIMEOUT,
        max_retries=LLM_MAX_RETRIES,
    )
```

`get_supervisor_chat_model()` 可删除；`SupervisorAgent.chat()` 和 `decide_slot_tool_calls()` 直接使用 `get_supervisor_model()`。

从 `SupervisorAgent` 删除 `_intent_chain`、`intent_chain`、影子线程池、影子方法和 `time` 的影子统计用途。`classify_intents()` 直接调用 `_predict_zero_shot()`；异常或空结果进入 `safe_fallback`。

- [ ] **Step 4: 运行监督者与配置测试并确认 GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests/test_supervisor_multi_intent.py tests/test_intent_config.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add finance_agent/agents/supervisor.py finance_agent/config.py tests/test_supervisor_multi_intent.py tests/test_intent_config.py
git commit -m "refactor: make mdeberta the sole intent classifier"
```

### Task 3: 将槽位解析完整迁入 tools

**Files:**
- Create: `finance_agent/tools/finance_slots.py`
- Delete: `finance_agent/agents/profile_extraction.py`
- Modify: `finance_agent/agents/__init__.py`
- Modify: `finance_agent/tools/__init__.py`
- Modify: `tests/test_profile_investment_goal.py`

**Interfaces:**
- Produces: `FinanceSlotsExtractor.extract_profile(...) -> dict`
- Produces: `FinanceSlotsExtractor.extract_slots(...) -> dict`
- Produces: `create_extract_finance_slots_tool(extractor, existing_profile=None, conversation_context="") -> BaseTool`
- Produces: `extract_investment_goal(message: str) -> str`

- [ ] **Step 1: 改写槽位测试导入并增加非 Agent 边界测试**

```python
from finance_agent.tools.finance_slots import (
    FinanceSlotsExtractor,
    create_extract_finance_slots_tool,
    extract_investment_goal,
)


def test_finance_slots_extractor_is_not_an_agent():
    extractor = FinanceSlotsExtractor()
    assert not hasattr(extractor, "handle")
    assert extractor.extract_slots("600519")["explicit_stock_codes"] == ["600519"]
```

将原 `SlotExtractionAgent()` 夹具改为 `FinanceSlotsExtractor()`。

- [ ] **Step 2: 运行测试并确认 RED**

Run: `.venv\Scripts\python.exe -m pytest tests/test_profile_investment_goal.py -q`

Expected: FAIL，`tools.finance_slots` 尚不存在。

- [ ] **Step 3: 创建工具模块并删除 Agent 模块**

迁移 `_PROFILE_EXTRACTION_PROMPT`、`extract_investment_goal()`、正则解析、LLM 补全、`extract_profile()`、`extract_explicit_stocks()`、`extract_slots()` 和工具工厂。

`FinanceSlotsExtractor` 不继承 `BaseFinanceAgent`，构造函数只初始化 `_extract_chain = None`。`extract_chain` 使用 `get_model_for_agent("slot_extraction")`。删除 `handle()`、共享内存和 checkpointer 参数。

更新 `tools/__init__.py` 导出三个公开接口；从 `agents/__init__.py` 删除旧导入与 `__all__` 项；删除旧文件。

- [ ] **Step 4: 运行槽位测试并确认 GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests/test_profile_investment_goal.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add finance_agent/tools/finance_slots.py finance_agent/agents/profile_extraction.py finance_agent/agents/__init__.py finance_agent/tools/__init__.py tests/test_profile_investment_goal.py
git commit -m "refactor: move finance slots into tools"
```

### Task 4: 更新编排器与 Tool Calling 测试

**Files:**
- Modify: `finance_agent/core/orchestrator.py`
- Modify: `tests/test_multi_intent_workflow.py`

**Interfaces:**
- Consumes: `FinanceSlotsExtractor`
- Produces: `AdvisorSystem.finance_slots_extractor`
- Preserves: `extract_finance_slots` Tool Call 参数、返回值和 `slot_tool_*` 状态

- [ ] **Step 1: 将集成测试改为新运行时名称**

把测试中的：

```python
system.slot_agent.extract_slots = fake_extract_slots
```

改为：

```python
system.finance_slots_extractor.extract_slots = fake_extract_slots
```

monkeypatch 工具工厂路径改为 `orchestrator_module.create_extract_finance_slots_tool`，并新增：

```python
def test_advisor_system_exposes_slot_tool_runtime_not_slot_agent():
    system = AdvisorSystem()
    assert isinstance(system.finance_slots_extractor, FinanceSlotsExtractor)
    assert not hasattr(system, "slot_agent")
```

- [ ] **Step 2: 运行集成测试并确认 RED**

Run: `.venv\Scripts\python.exe -m pytest tests/test_multi_intent_workflow.py -q`

Expected: FAIL，编排器仍暴露 `slot_agent` 并从 Agent 模块导入。

- [ ] **Step 3: 更新编排器**

从 `finance_agent.tools.finance_slots` 导入提取器和工具工厂；构造：

```python
self.finance_slots_extractor = FinanceSlotsExtractor()
```

所有工具工厂调用传入该对象，删除全部 `slot_agent` 引用。保持 trace、阶段名称和状态键不变。

- [ ] **Step 4: 运行 Tool Calling 与多意图测试并确认 GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests/test_multi_intent_workflow.py tests/test_slot_tool_routing.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add finance_agent/core/orchestrator.py tests/test_multi_intent_workflow.py
git commit -m "refactor: use finance slot tool runtime"
```

### Task 5: 全量回归与边界审计

**Files:**
- Test: `tests/test_zero_shot_intent_classifier.py`
- Test: `tests/test_supervisor_multi_intent.py`
- Test: `tests/test_intent_config.py`
- Test: `tests/test_profile_investment_goal.py`
- Test: `tests/test_multi_intent_workflow.py`

**Interfaces:**
- Verifies: 固定 NLI、监督者模块边界和槽位工具公开协议

- [ ] **Step 1: 运行后端全量测试**

Run: `.venv\Scripts\python.exe -m pytest -q`

Expected: 全部 PASS。

- [ ] **Step 2: 运行前端生产构建**

Run: `npm run build`

Working directory: `frontend`

Expected: exit code 0；允许既有 Rollup PURE 注释与大 chunk 警告。

- [ ] **Step 3: 审计旧模块与符号**

Run:

```powershell
Get-ChildItem -Recurse -File finance_agent,tests -Include *.py |
  Select-String -Pattern 'intent_classifier|profile_extraction|SlotExtractionAgent|ProfileExtractionAgent|slot_agent|INTENT_CLASSIFIER_MODE|INTENT_ZERO_SHOT_MODEL|get_intent_model'
```

Expected: 无匹配。该命令用于最终审计，不新增源码文本单元测试。

- [ ] **Step 4: 检查工作区隔离**

Run: `git diff --check` 和 `git status --short`

Expected: 无空白错误；提交范围不包含数据库、缓存、模型、`data/` 或无关 `.superdesign` 删除。

- [ ] **Step 5: 提交必要的回归修正**

若全量测试暴露迁移遗漏，只提交上述生产文件及对应测试：

```powershell
git add finance_agent/agents/supervisor.py finance_agent/config.py finance_agent/core/orchestrator.py finance_agent/agents/__init__.py finance_agent/tools/__init__.py finance_agent/tools/finance_slots.py tests
git commit -m "test: verify supervisor module boundaries"
```
