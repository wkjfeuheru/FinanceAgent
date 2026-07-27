# Supervisor Intent-Driven Workflow Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 LangGraph 后续工作流仅消费监督者生成的结构化意图执行计划，彻底移除用于选择工作流的关键词匹配。

**Architecture:** 扩展 `detected_intents` 项为“意图 + execution_mode + requires_slot_extraction”，由 `SupervisorAgent` 统一校验和规范化。编排器只读取这些枚举字段；主模型失败时改用多语言 NLI，双重失败时生成安全闲聊计划。

**Tech Stack:** Python 3.11、LangChain、LangGraph、pytest、现有 `ZeroShotIntentClassifier`

## Global Constraints

- 后续节点不得扫描用户原文或子请求关键词来选择工作流。
- 不新增第二次路由模型请求。
- 主模型失败时使用多语言 NLI；NLI 失败时固定降级为 `casual_chat/conversation`。
- 保留四类公开意图、现有 LangGraph 节点和槽位工具公开协议。
- 每个生产行为改动必须先写测试并观察预期失败，再写最小实现。
- 不提交数据库、模型、缓存、`data/` 或当前工作区内与本功能无关的删除。

---

## 文件结构

- Modify: `finance_agent/agents/supervisor.py` — 定义并校验结构化执行计划，负责模型/NLI/安全降级。
- Modify: `finance_agent/core/orchestrator.py` — 只消费执行计划，移除文本启发式路由。
- Modify: `tests/test_supervisor_multi_intent.py` — 覆盖协议规范化与无关键词降级链路。
- Modify: `tests/test_slot_tool_routing.py` — 覆盖结构化槽位授权。
- Modify: `tests/test_market_search_routing.py` — 覆盖执行模式到搜索分支的映射。
- Modify: `tests/test_multi_intent_workflow.py` — 覆盖多意图组合、隔离与端到端路由。

### Task 1: 扩展并规范化监督者执行计划

**Files:**
- Modify: `finance_agent/agents/supervisor.py:28-430`
- Modify: `tests/test_supervisor_multi_intent.py`

**Interfaces:**
- Produces: `normalize_intent_item(item: dict, fallback_query: str) -> dict | None`
- Produces: 每个合法意图项包含 `execution_mode: str` 与 `requires_slot_extraction: bool`
- Consumes: 现有 `intent/query/confidence/reason` 与 `_INTENTS`

- [ ] **Step 1: 写协议规范化失败测试**

在 `tests/test_supervisor_multi_intent.py` 中把模型夹具补成完整结构，并新增：

```python
def test_supervisor_normalizes_execution_plan_without_reading_query_keywords():
    supervisor = make_supervisor({
        "intents": [{
            "intent": "stock_recommendation",
            "query": "给我一些方向",
            "confidence": 0.95,
            "reason": "候选搜索",
            "execution_mode": "candidate_search",
            "requires_slot_extraction": False,
        }],
        "finance_related": True,
    })

    result = supervisor.plan_tasks("给我一些方向")

    assert result["intents"][0]["execution_mode"] == "candidate_search"
    assert result["intents"][0]["requires_slot_extraction"] is False
    assert result["task_plan"] == ["data_fetch", "fundamental_analysis", "compliance"]


def test_invalid_execution_mode_does_not_infer_route_from_query():
    supervisor = make_supervisor({
        "intents": [{
            "intent": "market_query",
            "query": "贵州茅台最近走势",
            "confidence": 0.95,
            "reason": "行情",
            "execution_mode": "unknown",
            "requires_slot_extraction": True,
        }],
        "finance_related": True,
    })

    result = supervisor.plan_tasks("贵州茅台最近走势")

    assert result["intents"][0]["execution_mode"] == "unsupported"
    assert result["intents"][0]["requires_slot_extraction"] is False
    assert result["task_plan"] == ["compliance"]
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `.venv\Scripts\python.exe -m pytest tests/test_supervisor_multi_intent.py::test_supervisor_normalizes_execution_plan_without_reading_query_keywords tests/test_supervisor_multi_intent.py::test_invalid_execution_mode_does_not_infer_route_from_query -q`

Expected: FAIL，现有结果缺少 `execution_mode`，且 `plan_tasks()` 仍按消息关键词选择节点。

- [ ] **Step 3: 写最小协议实现**

在 `supervisor.py` 定义合法映射并在合并意图前规范化：

```python
_EXECUTION_MODES = {
    "market_query": {"security_analysis": True, "market_overview": False},
    "stock_recommendation": {"candidate_search": False, "security_comparison": True},
    "asset_allocation": {"allocation": True},
    "casual_chat": {"conversation": False},
}


def normalize_intent_item(item: Dict[str, Any], fallback_query: str) -> Dict[str, Any] | None:
    intent = str(item.get("intent", "")).strip()
    if intent not in _INTENTS:
        return None
    mode = str(item.get("execution_mode", "")).strip()
    if mode not in _EXECUTION_MODES[intent]:
        mode = "unsupported" if intent in {"market_query", "stock_recommendation"} else next(iter(_EXECUTION_MODES[intent]))
    return {
        "intent": intent,
        "query": str(item.get("query", "")).strip() or fallback_query.strip(),
        "confidence": min(max(float(item.get("confidence", 0)), 0.0), 1.0),
        "reason": str(item.get("reason", "")).strip(),
        "execution_mode": mode,
        "requires_slot_extraction": (
            _EXECUTION_MODES[intent].get(mode, False)
        ),
    }
```

更新 `_SUPERVISOR_PROMPT` 的 JSON 协议和模式边界。重写 `plan_tasks()`：只按 `execution_mode` 添加 `data_fetch`、`fundamental_analysis`、`asset_allocation`、`casual_chat` 和 `compliance`，不得读取 `message`。

- [ ] **Step 4: 运行协议测试并确认 GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests/test_supervisor_multi_intent.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add finance_agent/agents/supervisor.py tests/test_supervisor_multi_intent.py
git commit -m "feat: add supervisor execution plans"
```

### Task 2: 用 NLI 与安全闲聊替代关键词分类兜底

**Files:**
- Modify: `finance_agent/agents/supervisor.py:270-430`
- Modify: `tests/test_supervisor_multi_intent.py`

**Interfaces:**
- Consumes: `ZeroShotIntentClassifier.predict(message, context, pending_allocation)`
- Produces: `_safe_casual_plan(message: str) -> dict`
- Produces: `intent_source` 只允许 `model`、`zero_shot`、`shadow` 语义相关值或 `safe_fallback`

- [ ] **Step 1: 写主模型失败和双重失败测试**

```python
class RaisingChain:
    def invoke(self, _payload):
        raise RuntimeError("primary unavailable")


def test_primary_failure_uses_zero_shot_without_keyword_rules(monkeypatch):
    agent = object.__new__(SupervisorAgent)
    agent._intent_chain = RaisingChain()
    agent._zero_shot_classifier = FakeZeroShotClassifier({
        "intents": [{
            "intent": "asset_allocation",
            "query": "替我安排这笔钱",
            "confidence": 0.88,
            "reason": "NLI",
        }],
        "finance_related": True,
    })
    monkeypatch.setattr(supervisor_module, "INTENT_CLASSIFIER_MODE", "model")

    result = agent.plan_tasks("替我安排这笔钱")

    assert result["intent_source"] == "zero_shot"
    assert result["intents"][0]["execution_mode"] == "allocation"


def test_primary_and_nli_failure_ignore_business_keywords(monkeypatch):
    class BrokenClassifier:
        def predict(self, *_args, **_kwargs):
            raise RuntimeError("nli unavailable")

    agent = object.__new__(SupervisorAgent)
    agent._intent_chain = RaisingChain()
    agent._zero_shot_classifier = BrokenClassifier()
    monkeypatch.setattr(supervisor_module, "INTENT_CLASSIFIER_MODE", "model")

    result = agent.plan_tasks("推荐股票并配置10万元")

    assert result["intent_source"] == "safe_fallback"
    assert result["finance_related"] is False
    assert result["intents"] == [{
        "intent": "casual_chat",
        "query": "推荐股票并配置10万元",
        "confidence": 0.0,
        "reason": "意图分类服务暂不可用",
        "execution_mode": "conversation",
        "requires_slot_extraction": False,
    }]
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `.venv\Scripts\python.exe -m pytest tests/test_supervisor_multi_intent.py -q`

Expected: FAIL，现有实现进入 `rule_fallback` 并从“推荐/配置”恢复业务意图。

- [ ] **Step 3: 实现无关键词降级**

删除 `_rule_intents()`、`_finance_related()`、`needs_asset_allocation()`、`needs_investment_profile()` 及 `_INVESTMENT_ADVICE_MARKERS`。主模型异常或无有效结果时调用 `_predict_zero_shot()`；NLI 结果通过固定意图映射补充执行模式：

```python
_NLI_MODE_DEFAULTS = {
    "market_query": "unsupported",
    "stock_recommendation": "candidate_search",
    "asset_allocation": "allocation",
    "casual_chat": "conversation",
}
```

若仍无有效结果，返回测试中的唯一 `safe_fallback` 结构。不得扫描 `message`。

- [ ] **Step 4: 运行监督者测试并确认 GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests/test_supervisor_multi_intent.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add finance_agent/agents/supervisor.py tests/test_supervisor_multi_intent.py
git commit -m "refactor: remove keyword intent fallback"
```

### Task 3: 让槽位与搜索节点只消费结构化执行计划

**Files:**
- Modify: `finance_agent/core/orchestrator.py:420-720`
- Modify: `finance_agent/agents/supervisor.py:120-200`
- Modify: `tests/test_slot_tool_routing.py`
- Modify: `tests/test_market_search_routing.py`

**Interfaces:**
- Produces: `SupervisorAgent.intent_plan_by_name(state, intent) -> dict`
- Consumes: `execution_mode` 与 `requires_slot_extraction`
- Removes: `needs_slot_extraction(intent, query)`、`needs_stock_screening(query)`、`needs_market_overview_search(query)`

- [ ] **Step 1: 用结构化计划改写槽位路由测试并确认其能捕获错误分支**

将 `tests/test_slot_tool_routing.py` 改为测试纯结构授权：

```python
from finance_agent.agents.supervisor import requires_slot_extraction


def test_slot_authorization_uses_plan_not_query_text():
    assert requires_slot_extraction({
        "intent": "market_query",
        "query": "完全相同的文本",
        "execution_mode": "security_analysis",
        "requires_slot_extraction": True,
    })
    assert not requires_slot_extraction({
        "intent": "market_query",
        "query": "完全相同的文本",
        "execution_mode": "market_overview",
        "requires_slot_extraction": False,
    })
```

将 `tests/test_market_search_routing.py` 改为通过完整的 `detected_intents` 驱动编排器，并断言同一 query 在 `market_overview` 时调用 `search_market_overview`、在 `security_analysis` 时不调用。

- [ ] **Step 2: 运行两个测试文件并确认 RED**

Run: `.venv\Scripts\python.exe -m pytest tests/test_slot_tool_routing.py tests/test_market_search_routing.py -q`

Expected: FAIL，现有导出函数和编排器仍读取 query 文本。

- [ ] **Step 3: 写最小结构路由实现**

在 `supervisor.py` 提供只校验已规范化计划的函数：

```python
def requires_slot_extraction(intent_plan: Dict[str, Any]) -> bool:
    intent = str(intent_plan.get("intent", ""))
    mode = str(intent_plan.get("execution_mode", ""))
    return bool(
        intent_plan.get("requires_slot_extraction")
        and _EXECUTION_MODES.get(intent, {}).get(mode) is True
    )
```

在 `orchestrator.py` 增加 `_intent_plan()`，使 `_slot_candidate_intents()` 与 `stock_resolution_handler()` 只读取计划：

```python
def _intent_plan(state: AdvisorState, intent: str) -> dict[str, Any]:
    for item in state.get("detected_intents", []) or []:
        if isinstance(item, dict) and item.get("intent") == intent:
            return item
    return {}
```

- `market_overview` 调 `search_market_overview()`。
- `candidate_search` 调 `search()`。
- `security_analysis`、`security_comparison` 使用槽位股票。
- `unsupported` 写入对应 `intent_results` 错误并继续其他意图。

删除旧文本路由函数及 import。

- [ ] **Step 4: 运行槽位和搜索测试并确认 GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests/test_slot_tool_routing.py tests/test_market_search_routing.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add finance_agent/agents/supervisor.py finance_agent/core/orchestrator.py tests/test_slot_tool_routing.py tests/test_market_search_routing.py
git commit -m "refactor: route workflows from supervisor plans"
```

### Task 4: 移除编排器中的取消关键词与历史计划歧义

**Files:**
- Modify: `finance_agent/core/orchestrator.py:380-460`
- Modify: `tests/test_multi_intent_workflow.py`

**Interfaces:**
- Consumes: 等待配置状态和监督者返回的 `asset_allocation/allocation` 或 `casual_chat/conversation`
- Produces: 取消等待配置时由监督者计划清理 `business_state`

- [ ] **Step 1: 写无取消关键词依赖的状态测试**

新增一个等待配置状态测试：监督者返回 `casual_chat/conversation`，query 使用不在旧词表中的“这件事到此为止”，断言 `business_state` 被清理且不进入资产配置；再新增监督者返回 `asset_allocation/allocation` 的短回复测试，断言继续配置流程。

```python
def test_pending_allocation_follows_supervisor_plan_without_cancel_markers():
    system = AdvisorSystem()
    system.supervisor.plan_tasks = lambda *_args, **_kwargs: {
        "intents": [{
            "intent": "casual_chat",
            "query": "这件事到此为止",
            "confidence": 0.99,
            "reason": "终止等待任务",
            "execution_mode": "conversation",
            "requires_slot_extraction": False,
        }],
        "finance_related": True,
        "intent_source": "model",
        "task_plan": ["casual_chat", "compliance"],
    }
    system.supervisor.chat = lambda *_args, **_kwargs: "已结束此前的配置任务。"
    state = make_state("这件事到此为止", "pending-plan-stop")
    state["business_state"] = {
        "status": "waiting_for_input",
        "intent": "asset_allocation",
        "missing_fields": ["budget_amount"],
    }
    result = system.graph.invoke(
        state,
        config={"configurable": {"thread_id": "pending-plan-stop"}},
    )
    assert result["business_state"] == {}
    assert "asset_allocation" not in result["task_plan"]
```

第二个测试使用相同入口，把计划替换为 `asset_allocation/allocation` 且 `requires_slot_extraction=True`，断言槽位工具获得短回复 query，并且 `business_state` 仍由配置状态守卫处理。两项测试都通过真实图入口断言最终状态，不复制生产判断逻辑。

- [ ] **Step 2: 运行目标测试并确认 RED**

Run: `.venv\Scripts\python.exe -m pytest tests/test_multi_intent_workflow.py -q`

Expected: FAIL，旧实现只匹配固定取消词，或仍从原文补推断配置意图。

- [ ] **Step 3: 实现计划驱动的等待状态迁移**

删除 `supervisor_handler` 内 `cancel_markers`。规则改为：等待状态存在且本轮计划不含 `asset_allocation/allocation` 时清理等待状态；包含该计划时恢复已解析股票并继续。这个判断只读取结构化状态。

- [ ] **Step 4: 运行多意图测试并确认 GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests/test_multi_intent_workflow.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add finance_agent/core/orchestrator.py tests/test_multi_intent_workflow.py
git commit -m "refactor: drive pending state from supervisor intent"
```

### Task 5: 全量回归与无关键词路由审计

**Files:**
- Test: `tests/test_supervisor_multi_intent.py`
- Test: `tests/test_multi_intent_workflow.py`

**Interfaces:**
- Verifies: 监督者计划是唯一工作流决策来源

- [ ] **Step 1: 运行后端全量测试**

Run: `.venv\Scripts\python.exe -m pytest -q`

Expected: 全部 PASS。

- [ ] **Step 2: 运行前端生产构建**

Run: `npm run build`

Working directory: `frontend`

Expected: exit code 0；允许现有 Rollup PURE 注释和大 chunk 警告，不允许 TypeScript 或构建错误。

- [ ] **Step 3: 审计生产路由调用点**

Run:

```powershell
Get-ChildItem -Recurse -File finance_agent -Include *.py |
  Select-String -Pattern 'needs_asset_allocation|needs_stock_screening|needs_market_overview_search|_INVESTMENT_ADVICE_MARKERS|_rule_intents|_finance_related'
```

Expected: 无生产代码匹配。此步骤是审计，不新增“源码文本必须恒定”的单元测试。

- [ ] **Step 4: 检查差异与工作区隔离**

Run: `git diff --check` 和 `git status --short`

Expected: 无空白错误；提交范围不包含数据库、缓存、模型、`data/` 或无关 `.superdesign` 删除。

- [ ] **Step 5: 提交必要的回归修正**

```powershell
git add finance_agent/agents/supervisor.py finance_agent/core/orchestrator.py tests/test_supervisor_multi_intent.py tests/test_slot_tool_routing.py tests/test_market_search_routing.py tests/test_multi_intent_workflow.py
git commit -m "test: cover intent-driven workflow routing"
```
