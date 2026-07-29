# FinanceAgent 全面架构重构 —— 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 FinanceAgent 从 1711 行巨石编排器重构为 6 个职责清晰的 Agent + 7 节点委托式 Graph + 按 Agent 划分的工具层

**Architecture:** 6 个 Agent 统一 `invoke(state) -> state` 接口；5 个用 ProceduralAgent，1 个用 ReActAgent（含安全上限）；orchestrator ~300 行只做图定义和路由；数据源从 tools/ 拆分到 data/ 层

**Tech Stack:** Python 3.10+, LangGraph, LangChain, DeepSeek API, BaoStock, EastMoney + Sina scraping, Redis, SQLite

**Spec:** `docs/superpowers/specs/2026-07-29-finance-agent-architecture-refactor-design.md`

## Global Constraints

- LangGraph StateGraph + checkpoint（SqliteSaver）必须保留
- SharedWorkingMemory 作为 Agent 间通信机制必须保留
- 现有数据源必须保留：BaoStock、东方财富 push2、新浪财经行业接口
- SSE 流式接口和进度回调必须保留
- DeepSeek API 作为唯一 LLM 提供方不变
- Python 3.10+ 不变
- 每步改动后通过 `python -m compileall -q finance_agent` 编译检查
- 现有测试在适配后全部通过

## File Structure

```
finanace_agent/
├── agents/
│   ├── __init__.py              ← modify: re-export 6 Agents
│   ├── base.py                  ← create: AgentProtocol / ProceduralAgent / ReActAgent
│   ├── supervisor.py            ← modify: inherit ProceduralAgent, remove decide_slot_tool_calls
│   ├── profile.py               ← create: ProfileAgent (from tools/finance_slots.py)
│   ├── data_fetch.py            ← modify: inherit ProceduralAgent, add MarketSearch integration
│   ├── stock_analysis.py        ← modify: inherit ReActAgent, add safety + format_analysis_report
│   ├── asset_allocation.py      ← modify: inherit ProceduralAgent, validate_prerequisites
│   └── compliance.py            ← modify: inherit ProceduralAgent, add synthesize_response
├── core/
│   ├── orchestrator.py          ← rewrite: ~300 lines, 7-node delegation
│   ├── state.py                 ← create: AdvisorState
│   ├── shared_state.py          ← unchanged
│   ├── memory.py                ← unchanged
│   └── database.py              ← unchanged
├── data/                        ← create directory
│   ├── __init__.py
│   ├── baostock.py              ← migrate from tools/baostock.py (no changes)
│   └── market.py                ← migrate from tools/market_data.py (no changes)
├── tools/
│   ├── __init__.py              ← modify: simplified exports
│   ├── fundamental.py           ← rename from tools/stock_data.py
│   ├── web_search.py            ← modify: import from data.market
│   ├── technical.py             ← rename from tools/technical_indicators.py
│   ├── allocation.py            ← unchanged
│   └── compliance.py            ← unchanged
├── api/                         ← unchanged
├── middleware/                   ← unchanged
├── config.py                    ← unchanged
└── main.py                      ← minimal import updates
```

---

### Task 1: Create `data/` layer (Baostock + Market sources)

**Files:**
- Create: `finance_agent/data/__init__.py`
- Create: `finance_agent/data/baostock.py` (copy from `tools/baostock.py`)
- Create: `finance_agent/data/market.py` (copy from `tools/market_data.py`)

**Interfaces:**
- Produces: `data.baostock.BaostockDataSource`, `.get_datasource()` — identical to original
- Produces: `data.market.EastMoneyMarketData`, `.SinaMarketData`, `.MarketDataError`, `.fetch_market_overview()`, `.fetch_sector_candidates()` — identical to original

- [ ] **Step 1:** `mkdir finance_agent\data`
- [ ] **Step 2:** Create `data/__init__.py` (docstring only)
- [ ] **Step 3:** `copy finance_agent\tools\baostock.py finance_agent\data\baostock.py` — check that all imports reference `finance_agent.config`, not `finance_agent.tools.*`
- [ ] **Step 4:** `copy finance_agent\tools\market_data.py finance_agent\data\market.py` — no internal imports to fix
- [ ] **Step 5:** Compile check: `python -m compileall -q finance_agent/data/`
- [ ] **Step 6:** Commit: `feat: create data/ layer with baostock and market data sources`

---

### Task 2: Rename tools files + update all import paths

**Files:**
- Create: `finance_agent/tools/fundamental.py` (copy from `tools/stock_data.py`)
- Create: `finance_agent/tools/technical.py` (copy from `tools/technical_indicators.py`)
- Modify: `finance_agent/tools/web_search.py` — import from `data.market` instead of `tools.market_data`
- Modify: `finance_agent/tools/__init__.py` — update all exports
- Modify: `finance_agent/agents/data_fetch.py` — `tools.stock_data` → `tools.fundamental`
- Modify: `finance_agent/agents/stock_analysis.py` — `tools.technical_indicators` → `tools.technical`
- Modify: `finance_agent/core/orchestrator.py` — `tools.web_search` (unchanged, verify)

- [ ] **Step 1:** Copy and fix import in `fundamental.py`: `from finance_agent.data.baostock import get_datasource`
- [ ] **Step 2:** Copy `technical.py` (no internal imports)
- [ ] **Step 3:** Fix `web_search.py` imports: `from finance_agent.data.market import EastMoneyMarketData, ...`
- [ ] **Step 4:** Rewrite `tools/__init__.py` (simplified — no more `finance_slots`, `baostock`, `market_data` exports)
- [ ] **Step 5:** Update imports in `agents/data_fetch.py` and `agents/stock_analysis.py`
- [ ] **Step 6:** Compile check + run existing tests: `python -m pytest tests/ -x --timeout=30 2>&1 | tail -20`
- [ ] **Step 7:** Commit: `refactor: rename tools files and update import paths`

---

### Task 3: Create Agent base classes (`agents/base.py`)

**Files:**
- Create: `finance_agent/agents/base.py`
- Test: `tests/test_agent_base.py`

**Interfaces:**
- Produces: `AgentProtocol` — abstract base, `invoke(state) -> state`
- Produces: `ProceduralAgent(AgentProtocol)` — procedural agent base
- Produces: `ReActAgent(AgentProtocol)` — ReAct agent with full safety mechanisms
- Consumes: `AdvisorState` from `core.state` (use `Dict[str, Any]` until Task 4)

- [ ] **Step 1:** Write `tests/test_agent_base.py` (test AgentProtocol abstract, ProceduralAgent invoke, ReActAgent config defaults, tool_call_health checks — same param detection, alternating loop detection, no-progress detection)
- [ ] **Step 2:** Run tests → FAIL (module not found)
- [ ] **Step 3:** Implement `agents/base.py`:
  - `AgentProtocol` with abstract `invoke(state) -> state`
  - `ProceduralAgent` with `shared_memory`, `_build_effective_message()`
  - `ReActAgent` with `max_reasoning_steps=10`, `per_invoke_timeout=90.0`, `tool_call_same_param_limit=3`, `_check_tool_call_health()`, thread timeout, `_fallback()`, lazy `self.agent` property
- [ ] **Step 4:** Run tests → PASS
- [ ] **Step 5:** Compile check + Commit: `feat: add AgentProtocol, ProceduralAgent, and ReActAgent base classes`

---

### Task 4: Create `core/state.py` with slimmed AdvisorState

**Files:**
- Create: `finance_agent/core/state.py`
- Modify: `finance_agent/core/orchestrator.py` — remove inline `AdvisorState` class, import from `core.state`
- Modify: `finance_agent/agents/base.py` — type annotations from `Dict` to `AdvisorState`

**Interfaces:**
- Produces: `AdvisorState(TypedDict)` — ~20 fields (user_message, chat_history, customer_id, task_plan, user_profile, resolved_stocks, candidate_stocks, sector_keywords, stock_data, stock_analysis, technical_analysis, allocation_result, agent_response, compliance_result, memory_context, shared_memory_snapshot, thread_id, run_id, detected_intents, intent_results)

- [ ] **Step 1:** Create `core/state.py` with the slimmed `AdvisorState(TypedDict)`
- [ ] **Step 2:** Remove inline `AdvisorState` class from orchestrator, import from `core.state`
- [ ] **Step 3:** Update `agents/base.py` type annotations
- [ ] **Step 4:** Compile check + test: `python -m pytest tests/ -x --timeout=30 2>&1 | tail -20`
- [ ] **Step 5:** Commit: `refactor: extract AdvisorState to core/state.py, slim to ~20 fields`

---

### Task 5: Refactor SupervisorAgent → ProceduralAgent

**Files:**
- Modify: `finance_agent/agents/supervisor.py`

**Interfaces:**
- Consumes: `ProceduralAgent` from `agents.base`
- Produces: `SupervisorAgent.invoke(state) -> state` — fills task_plan, detected_intents, intent_results, agent_response (chat/clarification)

- [ ] **Step 1:** Rewrite `agents/supervisor.py` — inherit `ProceduralAgent` instead of `BaseFinanceAgent`; keep `DeepSeekIntentClassifier` class, `classify_intents()`, `plan_tasks()`, `chat()`; add `invoke(state)` calling plan_tasks + optional chat; remove `decide_slot_tool_calls()`, `handle()`, `_get_tools()`, `_get_system_prompt()`
- [ ] **Step 2:** Compile check: `python -m compileall -q finance_agent/agents/supervisor.py`
- [ ] **Step 3:** Run supervisor tests: `python -m pytest tests/test_supervisor_multi_intent.py tests/test_intent_config.py -v --timeout=30`
- [ ] **Step 4:** Commit: `refactor: SupervisorAgent inherits ProceduralAgent, adds invoke()`

---

### Task 6: Create ProfileAgent (from tools/finance_slots.py)

**Files:**
- Create: `finance_agent/agents/profile.py`
- Test: `tests/test_profile_agent.py`

**Interfaces:**
- Consumes: `ProceduralAgent`, `FinanceSlotsExtractor` from `tools.finance_slots`
- Produces: `ProfileAgent.invoke(state) -> state` — fills user_profile, resolved_stocks, sector_keywords

- [ ] **Step 1:** Write `tests/test_profile_agent.py` (test sector keyword extraction, stock code extraction, risk preference, budget, existing profile merge)
- [ ] **Step 2:** Create `agents/profile.py` — inherit `ProceduralAgent`; `invoke(state)` calls `FinanceSlotsExtractor.extract_slots()` + `_extract_sector_keywords()`; publish to shared_memory
- [ ] **Step 3:** Run tests → PASS
- [ ] **Step 4:** Compile check + Commit: `feat: add ProfileAgent inheriting ProceduralAgent`

---

### Task 7: Refactor DataFetchAgent → ProceduralAgent

**Files:**
- Modify: `finance_agent/agents/data_fetch.py`

**Interfaces:**
- Consumes: `ProceduralAgent`, `data.baostock`, `tools.fundamental`, `tools.web_search.MarketSearch`
- Produces: `DataFetchAgent.invoke(state)`, `handle_single_stock(code)`, `aggregate(entries)`

- [ ] **Step 1:** Rewrite `agents/data_fetch.py` — inherit `ProceduralAgent`; add `invoke(state)` routing by execution_mode; `_handle_market_overview()` calls `MarketSearch.search_market_overview()`; `_handle_candidate_search()` calls `MarketSearch.search()`; keep `handle_single_stock(code)` unchanged; add `aggregate(entries)` for batch results; remove ReAct tools/prompt/handle
- [ ] **Step 2:** Compile check
- [ ] **Step 3:** Commit: `refactor: DataFetchAgent inherits ProceduralAgent, adds unified invoke()`

---

### Task 8: Refactor StockAnalysisAgent → ReActAgent

**Files:**
- Modify: `finance_agent/agents/stock_analysis.py`

**Interfaces:**
- Consumes: `ReActAgent`, `tools.technical`
- Produces: `StockAnalysisAgent.invoke(state)`, `handle_single_stock(code, user_message, memory_context)`, `aggregate(entries, state)`, `format_analysis_report(analysis, codes, screening)`

- [ ] **Step 1:** Rewrite `agents/stock_analysis.py` — inherit `ReActAgent`; set `max_reasoning_steps=6`, `per_invoke_timeout=60.0`; keep `_get_tools()`, `_get_system_prompt()`, `handle_single_stock()`; add `invoke(state)` for graph node; add `_fallback(state, reason)` with deterministic fundamental+technical fallback; add `aggregate(entries, state)` and `format_analysis_report()` from orchestrator; remove old `handle()`
- [ ] **Step 2:** Compile check
- [ ] **Step 3:** Commit: `refactor: StockAnalysisAgent inherits ReActAgent with safety config`

---

### Task 9: Refactor AssetAllocationAgent → ProceduralAgent

**Files:**
- Modify: `finance_agent/agents/asset_allocation.py`

**Interfaces:**
- Consumes: `ProceduralAgent`, `tools.allocation`
- Produces: `AssetAllocationAgent.invoke(state) -> state`, `validate_prerequisites(state) -> str | None`

- [ ] **Step 1:** Rewrite — inherit `ProceduralAgent`; `invoke(state)` validates prerequisites first, then runs MPT; `validate_prerequisites()` absorbed from orchestrator; remove ReAct tools/prompt
- [ ] **Step 2:** Compile check + Commit

---

### Task 10: Refactor ComplianceAgent → ProceduralAgent

**Files:**
- Modify: `finance_agent/agents/compliance.py`

**Interfaces:**
- Consumes: `ProceduralAgent`, `tools.compliance`
- Produces: `ComplianceAgent.invoke(state) -> state` — scan + compose + synthesize

- [ ] **Step 1:** Rewrite — inherit `ProceduralAgent`; `invoke(state)` does compose_intent_draft → synthesize_response (LLM thread-timeout) → sensitive word scan → append warnings; `_compose_intent_draft()`, `_synthesize_response()`, `_clean_response()` from orchestrator; remove old `review()`
- [ ] **Step 2:** Compile check + Commit

---

### Task 11: Update `agents/__init__.py`

**Files:**
- Modify: `finance_agent/agents/__init__.py`

- [ ] **Step 1:** Rewrite to export 6 Agents
- [ ] **Step 2:** Compile check + Commit

---

### Task 12: Rewrite Orchestrator (7-node delegation)

**Files:**
- Modify: `finance_agent/core/orchestrator.py`

- [ ] **Step 1:** Rewrite `_build_graph()` — 7 nodes: supervisor, profile, data_fetch_batch, stock_analysis_batch, asset_allocation, compliance; 3 conditional routing functions
- [ ] **Step 2:** Implement `_data_fetch_batch_handler` and `_stock_analysis_batch_handler` with `@task` fan-out
- [ ] **Step 3:** Keep public API unchanged (`handle_message`, `handle_message_stream`, `reset_session`, `get_user_profile`, etc.)
- [ ] **Step 4:** Compile check + Commit

---

### Task 13: Clean up old files

**Files:**
- Delete: `tools/stock_data.py`, `tools/technical_indicators.py`, `tools/baostock.py`, `tools/market_data.py`, `tools/finance_slots.py`
- Modify: `finance_agent/main.py` (if needed)

- [ ] **Step 1:** `git rm` all migrated files
- [ ] **Step 2:** Search for residual references: `rg "tools\.(stock_data|technical_indicators|baostock|market_data|finance_slots)" finance_agent/`
- [ ] **Step 3:** Full compile check: `python -m compileall -q finance_agent/`
- [ ] **Step 4:** Commit

---

### Task 14: Adapt existing tests

**Files:**
- Modify: `tests/test_intent_config.py`, `tests/test_multi_intent_workflow.py`, `tests/test_supervisor_multi_intent.py`, etc.

- [ ] **Step 1:** Run all tests, collect failures
- [ ] **Step 2:** Fix imports, Agent instantiation, call patterns (`invoke(state)` instead of `.handle()`), State field assertions
- [ ] **Step 3:** Confirm all tests pass
- [ ] **Step 4:** Commit

---

### Task 15: Integration tests (critical paths)

**Files:**
- Create: `tests/test_refactored_workflow.py`

- [ ] **Step 1:** Write tests covering: market_overview path, security_analysis path, candidate_search path, prerequisite validation (missing fields → prompt), ReAct safety limits (duplicate param detection, alternating loop detection)
- [ ] **Step 2:** Run tests → PASS
- [ ] **Step 3:** Commit

---

### Task 16: Final verification + docs

- [ ] **Step 1:** Full compile + test: `python -m compileall -q finance_agent/ && python -m pytest tests/ --timeout=60 -v`
- [ ] **Step 2:** Update README.md architecture section
- [ ] **Step 3:** Final commit

---
