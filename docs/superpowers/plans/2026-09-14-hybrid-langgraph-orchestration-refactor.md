# Hybrid LangGraph Orchestration Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 FinanceAgent 渐进迁移为“默认会话 ReAct、单领域 Domain ReAct、复合领域 Plan-and-Execute”的 LangGraph 编排，并提供本地 FAQ RAG、Celery 量化任务、可恢复 checkpoint 与统一合规出口。

**Architecture:** 在现有 `AdvisorSystem` 外保留兼容 Facade，在 `finance_agent/orchestrator/` 下新增强类型契约、Root Graph、四个受限 ReAct 子图、Plan-and-Execute、FAQ、Celery 和合规子图。功能开关先使新路径可单独验证，所有阶段完成并通过兼容测试后再移除旧的 Manager/专业 Agent 编排。

**Tech Stack:** Python 3.10+、FastAPI、LangGraph、Pydantic、PostgreSQL、pgvector、Redis、Celery、sentence-transformers、pytest。

## Global Constraints

- 顶层业务领域只能是 `stock_research`、`market_insight`、`product_research`；casual chat 与 FAQ 是空领域的默认会话路径。
- Conversation ReAct 与三个 Domain ReAct 的循环上限均为 4。
- Plan-and-Execute 最多 8 个任务、最多 2 次重新规划；Root Graph 的 `recursion_limit` 为 32。
- LLM 只能分类、规划、选择白名单工具和生成受约束叙述；取数、指标、评分、筛选、回测和重放必须由确定性工具完成。
- `thread_id` 固定为 `v1:{authenticated_customer_id}:{conversation_id}`；`conversation_id` 是对外 session ID，不能信任请求体中的 customer ID。
- State 不存 DataFrame、长 K 线、模型/数据库/Celery 客户端或 SSE callback；只存 `ArtifactRef` 和可 JSON 序列化的强类型数据。
- CPU 密集任务通过 Celery 的独立 Redis DB 与 `finance.quant` 队列执行；行情和数据库查询保持在线 I/O 工具。
- 所有可见输出必须经过合规子图；合规改写最多一次，改写不得改变事实、数值和引用。
- 不能在新路径异常时静默返回旧路径；任何降级必须在运行状态、警告和审计中明确记录。
- 现有 `/api/chat`、`/api/chat/stream` 和结构化响应字段必须兼容；新增字段只能追加。

---

## File Structure

| 路径 | 职责 |
| --- | --- |
| `finance_agent/orchestrator/contracts.py` | 新编排的枚举、Pydantic 契约、状态 reducer。 |
| `finance_agent/orchestrator/thread_key.py` | 复合 `thread_id` 构造、解析和旧键兼容读取策略。 |
| `finance_agent/orchestrator/root_graph.py` | Root Graph、领域路由、单领域任务构造与兼容投影。 |
| `finance_agent/orchestrator/react.py` | 四轮受限 ReAct 的通用循环与工具协议。 |
| `finance_agent/orchestrator/plan_execute.py` | 强类型计划校验、`Send` 扇出、依赖调度和重新规划。 |
| `finance_agent/orchestrator/domains/{stock,market,product}.py` | 三个领域 ReAct 子图与现有确定性 pipeline 的节点适配。 |
| `finance_agent/orchestrator/compliance.py` | 确定性规则、语义校验、一次改写和最终阻断。 |
| `finance_agent/orchestrator/quant.py` | `QuantGateway` 接口与 Celery/内存 Adapter。 |
| `finance_agent/orchestrator/resume.py` | 等待异步任务的恢复协调器。 |
| `finance_agent/faq/*` | FAQ 文档解析、本地 embedding、pgvector repository、索引 CLI 和检索工具。 |
| `finance_agent/celery_app.py`、`finance_agent/tasks/quant.py` | Celery 应用与纯计算任务入口。 |
| `sql/008_hybrid_orchestration.sql` | pgvector、FAQ、异步任务与索引版本 schema。 |
| `docs/faq/*.md` | 投资规则 FAQ 原文。 |
| `tests/test_*_v2.py` | 新系统的单元、集成和兼容回归测试。 |

### Task 1: 建立新编排契约、预算与复合线程键

**Files:**

- Create: `finance_agent/orchestrator/contracts.py`
- Create: `finance_agent/orchestrator/thread_key.py`
- Modify: `finance_agent/config.py:39-40, 80-120`
- Modify: `finance_agent/contracts/schema/enums.py:8-67`
- Test: `tests/test_orchestrator_contracts_v2.py`

**Interfaces:**

- Produces `BusinessDomain`, `ExecutionMode`, `RunBudgets`, `PlanTask`, `DomainOutcome`, `AsyncJobRef`, `ComplianceDecision`, `NodeError` and `build_thread_id(customer_id, conversation_id) -> str`.
- Consumed by every subsequent graph, FAQ, Celery and API task.

- [ ] **Step 1: Write failing contract and key tests**

```python
from finance_agent.orchestrator.contracts import BusinessDomain, RunBudgets
from finance_agent.orchestrator.thread_key import build_thread_id, parse_thread_id

def test_thread_key_is_customer_scoped_and_round_trips():
    value = build_thread_id("CUST000001", "conv-1")
    assert value == "v1:CUST000001:conv-1"
    assert parse_thread_id(value) == ("CUST000001", "conv-1")

def test_budget_rejects_values_above_confirmed_limits():
    assert RunBudgets().react_steps == 4
    with pytest.raises(ValidationError):
        RunBudgets(react_steps=5)
```

- [ ] **Step 2: Run the contract tests and verify failure**

Run: `pytest tests/test_orchestrator_contracts_v2.py -v`

Expected: FAIL because the new modules do not exist.

- [ ] **Step 3: Add the minimal contracts and configuration**

```python
class BusinessDomain(str, Enum):
    STOCK_RESEARCH = "stock_research"
    MARKET_INSIGHT = "market_insight"
    PRODUCT_RESEARCH = "product_research"

class RunBudgets(BaseModel):
    react_steps: int = Field(default=4, ge=0, le=4)
    plan_tasks: int = Field(default=8, ge=0, le=8)
    replans: int = Field(default=2, ge=0, le=2)
    compliance_rewrites: int = Field(default=1, ge=0, le=1)
    graph_steps: int = Field(default=32, ge=1, le=32)

def build_thread_id(customer_id: str, conversation_id: str) -> str:
    if not customer_id or ":" in customer_id or not conversation_id or ":" in conversation_id:
        raise ValueError("invalid thread key component")
    return f"v1:{customer_id.upper()}:{conversation_id}"

class ArtifactRef(BaseModel):
    uri: str
    content_hash: str = ""
    media_type: str = "application/json"

class AsyncJobRef(BaseModel):
    job_id: str
    kind: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    task_id: str

class PlanTask(BaseModel):
    task_id: str
    domain: BusinessDomain
    goal: str
    instruction: str
    depends_on: list[str] = Field(default_factory=list)
    input_refs: list[ArtifactRef] = Field(default_factory=list)
    expected_output: str

class DomainOutcome(BaseModel):
    task_id: str
    domain: BusinessDomain
    status: Literal["success", "partial", "processing", "failed"]
    summary: str
    structured_data: dict[str, Any] = Field(default_factory=dict)
    evidence: list[ArtifactRef] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    pending_jobs: list[AsyncJobRef] = Field(default_factory=list)

class DomainTaskContext(BaseModel):
    task: PlanTask
    thread_id: str
    customer_id: str
    conversation_id: str
    user_message: str
    upstream_results: dict[str, DomainOutcome] = Field(default_factory=dict)

class ExecutionPlan(BaseModel):
    tasks: list[PlanTask]

class PlanDecision(BaseModel):
    action: Literal["dispatch", "replan", "finish"]
    plan: ExecutionPlan | None = None

class RoutingDecision(BaseModel):
    domains: list[BusinessDomain]
    execution_mode: Literal["conversation", "domain_react", "plan_execute", "clarify"]
    clarification: str = ""

class ReactDecision(BaseModel):
    action: Literal["tool", "final"]
    tool_name: str = ""
    tool_input: dict[str, Any] = Field(default_factory=dict)
    final_text: str = ""
```

Add `ORCHESTRATION_V2_ENABLED=false`, all five budget environment variables, `CELERY_REDIS_DB=1`, `CELERY_QUANT_QUEUE=finance.quant`, and local FAQ embedding configuration to `config.py`. Keep existing values as the legacy defaults.

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/test_orchestrator_contracts_v2.py -v`

Expected: PASS.

- [ ] **Step 5: Commit the isolated contract baseline**

```bash
git add finance_agent/orchestrator/contracts.py finance_agent/orchestrator/thread_key.py finance_agent/config.py finance_agent/contracts/schema/enums.py tests/test_orchestrator_contracts_v2.py
git commit -m "feat: add orchestration v2 contracts"
```

### Task 2: 添加 pgvector、FAQ 与异步运行持久化

**Files:**

- Create: `sql/008_hybrid_orchestration.sql`
- Modify: `finance_agent/data/postgres_schema.py:12-53`
- Modify: `finance_agent/data/postgres_stores.py:42-76, 147-297`
- Create: `finance_agent/faq/repository.py`
- Test: `tests/test_faq_schema.py`
- Test: `tests/test_thread_key_migration.py`

**Interfaces:**

- Produces `FaqRepository.publish_index(...)`, `FaqRepository.search(...)`, `AsyncRunRepository.save_job_ref(...)`, and `load_checkpoint_with_legacy_fallback(...)`.
- Consumes `ThreadKey` and FAQ contracts from Task 1.

- [ ] **Step 1: Write failing database-contract tests**

```python
def test_faq_schema_contains_versioned_vector_chunks(schema_sql: str):
    assert "CREATE EXTENSION IF NOT EXISTS vector" in schema_sql
    assert "finance.faq_chunks" in schema_sql
    assert "embedding vector(512)" in schema_sql

def test_legacy_checkpoint_is_only_read_for_the_owner(fake_store):
    fake_store.put_legacy("conv-1", {"customer_id": "CUST1"})
    assert fake_store.load("CUST1", "conv-1") is not None
    assert fake_store.load("CUST2", "conv-1") is None
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_faq_schema.py tests/test_thread_key_migration.py -v`

Expected: FAIL because schema and repositories are absent.

- [ ] **Step 3: Implement migration and repositories**

Create `finance.faq_documents`, `finance.faq_chunks`, `finance.faq_index_versions`, and `finance.async_jobs`. `faq_chunks` must use `vector(512)`, `content_hash`, `is_active`, `faq_id`, source path, chunk ordinal, tsvector text index, and cosine HNSW index. `async_jobs` must persist `job_id`, `thread_id`, `run_id`, `task_id`, `status`, idempotency key, result reference, timestamps and a unique idempotency key.

`load_checkpoint_with_legacy_fallback(customer_id, conversation_id)` must attempt `v1:{customer_id}:{conversation_id}` first. It may inspect the old `conversation_id` checkpoint only after `PostgresBusinessStore.get_conversation(conversation_id, customer_id)` succeeds; a valid legacy snapshot must be copied into the new key before returning.

Use this repository seam so graph code never emits SQL directly:

```python
class AsyncRunRepository(Protocol):
    def save_job_ref(self, *, customer_id: str, thread_id: str, run_id: str, job: AsyncJobRef, idempotency_key: str) -> None: ...
    def get_job_ref(self, job_id: str, customer_id: str) -> AsyncJobRef | None: ...
```

- [ ] **Step 4: Run schema and migration tests**

Run: `pytest tests/test_faq_schema.py tests/test_thread_key_migration.py tests/test_postgres_schema.py -v`

Expected: PASS.

- [ ] **Step 5: Commit persistence changes**

```bash
git add sql/008_hybrid_orchestration.sql finance_agent/data/postgres_schema.py finance_agent/data/postgres_stores.py finance_agent/faq/repository.py tests/test_faq_schema.py tests/test_thread_key_migration.py
git commit -m "feat: persist faq and async orchestration state"
```

### Task 3: 实现本地 FAQ 文档、embedding 与混合检索

**Files:**

- Create: `docs/faq/investment-basics.md`
- Create: `docs/faq/risk-and-compliance.md`
- Create: `docs/faq/trading-rules.md`
- Create: `finance_agent/faq/contracts.py`
- Create: `finance_agent/faq/documents.py`
- Create: `finance_agent/faq/embeddings.py`
- Create: `finance_agent/faq/indexer.py`
- Create: `finance_agent/faq/retriever.py`
- Create: `finance_agent/faq/__main__.py`
- Modify: `pyproject.toml:23-42`
- Modify: `requirements.txt:1-22`
- Test: `tests/test_faq_documents.py`
- Test: `tests/test_faq_retriever.py`

**Interfaces:**

- Produces `EmbeddingProvider.embed_documents(texts)`, `EmbeddingProvider.embed_query(text)`, `index_faq_documents(root)`, and `FaqRetriever.search(query, top_k=4)`.
- `FaqRetriever.search` returns `FaqSearchResult(status, matches)` where every match includes FAQ ID, chunk ID, score, index version and source path.

- [ ] **Step 1: Write failing parser and retriever tests**

```python
def test_parser_keeps_each_faq_question_and_answer_in_one_chunk(tmp_path):
    chunks = parse_faq_markdown(tmp_path / "investment-basics.md")
    assert chunks[0].faq_id == "FAQ-001"
    assert "保证收益" in chunks[0].content

def test_retriever_returns_not_found_below_threshold(fake_repository):
    result = FaqRetriever(fake_repository, FakeEmbedding()).search("如何绕过涨跌停？")
    assert result.status == "not_found"
    assert result.matches == []
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_faq_documents.py tests/test_faq_retriever.py -v`

Expected: FAIL because FAQ modules and documents are absent.

- [ ] **Step 3: Implement deterministic FAQ ingestion**

Use headings in the exact form `## FAQ-001 标题`; reject duplicate IDs, heading-only questions, empty answers and malformed heading IDs. Store one heading section as one chunk. Implement a lazy CPU-only `SentenceTransformerEmbeddingProvider` pinned to `BAAI/bge-small-zh-v1.5`; do not download models in FastAPI startup. Add explicit CLI:

```bash
python -m finance_agent.faq index --root docs/faq --model-cache-dir .cache/models
```

The CLI must validate all three files before publishing an index version. Write embeddings and PostgreSQL full-text values in one transaction; only then mark the new version active and old chunks inactive. `FaqRetriever` performs vector top-12 plus keyword top-12, fuses by normalized reciprocal rank, filters scores below `FAQ_MIN_SCORE`, and returns at most four matches.

Define the retriever result in `finance_agent/faq/contracts.py`:

```python
class FaqSearchMatch(BaseModel):
    faq_id: str
    chunk_id: str
    score: float
    index_version: str
    source_path: str
    content: str

class FaqSearchResult(BaseModel):
    status: Literal["found", "not_found"]
    matches: list[FaqSearchMatch] = Field(default_factory=list)
```

- [ ] **Step 4: Run FAQ tests**

Run: `pytest tests/test_faq_documents.py tests/test_faq_retriever.py -v`

Expected: PASS using a fake embedding provider and in-memory repository; no network/model download.

- [ ] **Step 5: Commit FAQ RAG**

```bash
git add docs/faq finance_agent/faq pyproject.toml requirements.txt tests/test_faq_documents.py tests/test_faq_retriever.py
git commit -m "feat: add local faq retrieval"
```

### Task 4: 实现四轮受限 ReAct 内核与会话子图

**Files:**

- Create: `finance_agent/orchestrator/react.py`
- Create: `finance_agent/orchestrator/conversation_graph.py`
- Modify: `finance_agent/agents/casual_chat.py:1-61`
- Test: `tests/test_react_loop.py`
- Test: `tests/test_conversation_graph.py`

**Interfaces:**

- Produces `ToolSpec(name, input_model, output_model, handler)`, `run_bounded_react(...)`, and `build_conversation_graph(retriever, model)`.
- Consumes `RunBudgets`, `FaqRetriever`, and `DomainOutcome` from Tasks 1 and 3.

- [ ] **Step 1: Write failing loop-limit and tool-whitelist tests**

```python
def test_react_stops_after_four_observations():
    outcome = run_bounded_react(always_calls_tool_model(), tools={"faq_search": fake_tool}, budget=4)
    assert outcome.status == "partial"
    assert outcome.metadata["react_steps"] == 4

def test_conversation_graph_rejects_non_whitelisted_tool():
    result = build_conversation_graph(fake_retriever, model_calling("stock_quote")).invoke(base_state())
    assert result["final_response"] == "暂时无法执行该操作。"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_react_loop.py tests/test_conversation_graph.py -v`

Expected: FAIL because no ReAct kernel exists.

- [ ] **Step 3: Implement the loop and graph**

The loop must parse only a Pydantic `ReactDecision(action: Literal["tool", "final"], tool_name, tool_input, final_text)` response. Validate `tool_name` against the supplied mapping and validate input/output models before adding an observation. The conversation graph exposes only `faq_search`; its no-match observation must state that the FAQ knowledge base has no reliable answer. Refactor `casual_chat.py` into a pure final-text helper or remove its use from the new path; it must not own a graph or checkpoint.

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/test_react_loop.py tests/test_conversation_graph.py tests/test_no_silent_fallbacks.py -v`

Expected: PASS.

- [ ] **Step 5: Commit ReAct foundation**

```bash
git add finance_agent/orchestrator/react.py finance_agent/orchestrator/conversation_graph.py finance_agent/agents/casual_chat.py tests/test_react_loop.py tests/test_conversation_graph.py
git commit -m "feat: add bounded conversation react graph"
```

### Task 5: 接入 Root Graph、三领域路由与复合线程键

**Files:**

- Create: `finance_agent/orchestrator/root_graph.py`
- Modify: `finance_agent/orchestrator/orchestrator.py:51-547, 562-725`
- Modify: `finance_agent/agents/supervisor.py:80-498`
- Modify: `finance_agent/api/routes.py:147-225`
- Modify: `finance_agent/api/schemas.py:14-83`
- Test: `tests/test_root_graph_routing.py`
- Test: `tests/test_multitenant_checkpoints.py`
- Test: `tests/test_api_compatibility_v2.py`

**Interfaces:**

- Produces `classify_domains(message, context) -> RoutingDecision`, `build_root_graph(dependencies)`, and `AdvisorSystem.handle_message_v2(...)` behind `ORCHESTRATION_V2_ENABLED`.
- Consumes Task 1 contracts, Task 4 conversation graph, existing `SlotExtractor`, and existing authenticated customer ID from API routes.

- [ ] **Step 1: Write failing routing and isolation tests**

```python
@pytest.mark.parametrize(("message", "domains", "mode"), [
    ("你好", [], "conversation"),
    ("分析贵州茅台", ["stock_research"], "domain_react"),
    ("市场情绪和基金产品怎么搭配", ["market_insight", "product_research"], "plan_execute"),
])
def test_root_routes_by_domain_count(message, domains, mode):
    assert classify_domains_with_fake_model(message).domains == domains
    assert classify_domains_with_fake_model(message).execution_mode.value == mode

def test_same_conversation_id_isolated_by_customer(checkpointer):
    assert build_thread_id("CUST1", "same") != build_thread_id("CUST2", "same")
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_root_graph_routing.py tests/test_multitenant_checkpoints.py tests/test_api_compatibility_v2.py -v`

Expected: FAIL because Root Graph and v2 path are absent.

- [ ] **Step 3: Implement explicit routing without legacy fallback**

Map current classifier output into the three domains: both `stock_analysis` and `stock_recommendation` map to `stock_research`; `market_insight` and `product_analysis` map directly; `casual_chat` maps to no domain. Refactor `ManagerAgent` into a classifier/synthesis helper only, then remove it from the v2 execution path.

Construct `thread_id` solely from the authenticated `customer_id` and `conversation_id`; do not derive it from request body or append task IDs. Compile Root Graph with `recursion_limit=32`. Root Graph must create `single:{run_id}:{domain}` for one-domain paths and return a structured clarification state for low confidence.

Keep the old `handle_message` path selected only when `ORCHESTRATION_V2_ENABLED` is false. When true, an exception in v2 returns a safe failed response with `run_status="failed"`; it must not invoke legacy processing.

- [ ] **Step 4: Run focused and legacy regression tests**

Run: `pytest tests/test_root_graph_routing.py tests/test_multitenant_checkpoints.py tests/test_api_compatibility_v2.py tests/test_runtime_controls.py -v`

Expected: PASS.

- [ ] **Step 5: Commit Root Graph routing**

```bash
git add finance_agent/orchestrator/root_graph.py finance_agent/orchestrator/orchestrator.py finance_agent/agents/supervisor.py finance_agent/api/routes.py finance_agent/api/schemas.py tests/test_root_graph_routing.py tests/test_multitenant_checkpoints.py tests/test_api_compatibility_v2.py
git commit -m "feat: route v2 orchestration by business domain"
```

### Task 6: 将三个专业 Agent 改造为 Domain ReAct 子图

**Files:**

- Create: `finance_agent/orchestrator/domains/__init__.py`
- Create: `finance_agent/orchestrator/domains/stock.py`
- Create: `finance_agent/orchestrator/domains/market.py`
- Create: `finance_agent/orchestrator/domains/product.py`
- Modify: `finance_agent/agents/stock_analysis.py:71-524`
- Modify: `finance_agent/agents/market_insight.py:156-377`
- Modify: `finance_agent/agents/product_analysis.py:38-194`
- Test: `tests/test_stock_domain_graph.py`
- Test: `tests/test_market_domain_graph.py`
- Test: `tests/test_product_domain_graph.py`

**Interfaces:**

- Produces `build_stock_domain_graph(deps)`, `build_market_domain_graph(deps)`, `build_product_domain_graph(deps)`; every graph receives `DomainTaskContext` and returns `DomainOutcome`.
- Consumes the generic ReAct loop from Task 4 and current deterministic research/product/market pipeline functions.

- [ ] **Step 1: Write failing graph tests with fake tools**

```python
def test_stock_domain_selects_candidate_search_for_recommendation():
    result = build_stock_domain_graph(fake_stock_tools()).invoke(stock_context(goal="recommend"))
    assert result["domain_outcome"].structured_data["mode"] == "candidate_search"

def test_market_domain_cannot_call_product_tool():
    result = build_market_domain_graph(fake_market_tools()).invoke(market_context())
    assert "product_lookup" not in result["tool_trace"]

def test_product_domain_returns_uniform_outcome():
    outcome = build_product_domain_graph(fake_product_tools()).invoke(product_context())["domain_outcome"]
    assert outcome.domain.value == "product_research"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_stock_domain_graph.py tests/test_market_domain_graph.py tests/test_product_domain_graph.py -v`

Expected: FAIL because domain graph builders do not exist.

- [ ] **Step 3: Extract deterministic operations into graph nodes**

Move reusable code from the three Agent classes into node functions; do not wrap the classes as hidden v2 Agents. Stock nodes call the current `ResearchPipeline`, technical indicator tool, theme screener and data provider adapters. Market nodes call existing collectors and `PolicyImpactInterpreter` only for the constrained policy explanation. Product nodes call `ProductResearchPipeline` and product-library tools.

For each graph expose a small tool whitelist: stock uses resolution/fetch/research/quant operations, market uses the four market collectors and policy interpretation, product uses product lookup/evaluation. Each tool output is validated and transformed to `DomainOutcome`; failure returns safe limitations rather than raw exceptions.

- [ ] **Step 4: Run focused and existing domain regressions**

Run: `pytest tests/test_stock_domain_graph.py tests/test_market_domain_graph.py tests/test_product_domain_graph.py tests/test_stock_analysis_e2e.py tests/test_product_analysis_agent.py tests/test_market_insight.py -v`

Expected: PASS.

- [ ] **Step 5: Commit domain subgraphs**

```bash
git add finance_agent/orchestrator/domains finance_agent/agents/stock_analysis.py finance_agent/agents/market_insight.py finance_agent/agents/product_analysis.py tests/test_stock_domain_graph.py tests/test_market_domain_graph.py tests/test_product_domain_graph.py
git commit -m "feat: add domain react subgraphs"
```

### Task 7: 实现复合意图 Plan-and-Execute 与统一 `Send` 调度

**Files:**

- Create: `finance_agent/orchestrator/plan_execute.py`
- Modify: `finance_agent/orchestrator/root_graph.py`
- Modify: `finance_agent/orchestrator/scheduler.py:19-184`
- Test: `tests/test_plan_execute_graph.py`
- Modify: `tests/test_orchestrator_fanout.py:1-234`

**Interfaces:**

- Produces `validate_execution_plan(plan)`, `dispatch_ready_tasks(state) -> list[Send]`, and `evaluate_plan_results(state) -> PlanDecision`.
- Consumes Domain Graph builders from Task 6 and `PlanTask` from Task 1.

- [ ] **Step 1: Write failing plan-validation and fan-out tests**

```python
def test_plan_rejects_more_than_eight_tasks():
    plan = ExecutionPlan(tasks=[make_task(str(i)) for i in range(9)])
    assert validate_execution_plan(plan).error.code == "plan_task_limit"

def test_only_ready_tasks_are_sent_and_dependencies_receive_results():
    state = plan_state(tasks=[task("a"), task("b", depends_on=["a"])])
    sends = dispatch_ready_tasks(state)
    assert [send.arg["task_id"] for send in sends] == ["a"]
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_plan_execute_graph.py tests/test_orchestrator_fanout.py -v`

Expected: FAIL because the unified planner does not exist.

- [ ] **Step 3: Implement strong plan validation and graph routing**

Validate task count, unique IDs, allowed domains, acyclic dependencies, dependency references, task budget and required `expected_output`. Use LangGraph `Send` only from `dispatch_ready_tasks`; the send payload must contain `task_id`, `domain`, goal, instruction, upstream `DomainOutcome` values and the unchanged root `thread_id`.

Merge results by `task_id`. `evaluate_plan_results` either finishes, marks partial, or requests one of the two available replans. Replanning must preserve completed tasks and may only add tasks while total count remains at eight. Remove the old scheduler from the v2 graph; keep it only for the feature-flagged legacy path until Task 10.

- [ ] **Step 4: Run scheduling tests**

Run: `pytest tests/test_plan_execute_graph.py tests/test_orchestrator_fanout.py tests/test_task_scheduler.py -v`

Expected: PASS.

- [ ] **Step 5: Commit Plan-and-Execute**

```bash
git add finance_agent/orchestrator/plan_execute.py finance_agent/orchestrator/root_graph.py finance_agent/orchestrator/scheduler.py tests/test_plan_execute_graph.py tests/test_orchestrator_fanout.py
git commit -m "feat: add cross-domain plan and execute graph"
```

### Task 8: 引入 Celery Quant Gateway 与 checkpoint 恢复

**Files:**

- Create: `finance_agent/celery_app.py`
- Create: `finance_agent/tasks/__init__.py`
- Create: `finance_agent/tasks/quant.py`
- Create: `finance_agent/orchestrator/quant.py`
- Create: `finance_agent/orchestrator/resume.py`
- Modify: `finance_agent/orchestrator/domains/stock.py`
- Modify: `finance_agent/config.py`
- Modify: `pyproject.toml`
- Modify: `requirements.txt`
- Test: `tests/test_quant_gateway.py`
- Test: `tests/test_resume_coordinator.py`

**Interfaces:**

- Produces `QuantGateway.submit(kind, payload, idempotency_key) -> AsyncJobRef`, `status(job_id)`, `result(job_id)`, and `ResumeCoordinator.resume_ready(thread_id)`.
- Consumes `AsyncJobRef`, async repository and root graph from Tasks 1, 2 and 5.

- [ ] **Step 1: Write failing gateway and resume tests**

```python
def test_gateway_reuses_idempotent_quant_job(memory_gateway):
    first = memory_gateway.submit("technical_indicators", {"close": [1, 2]}, "key-1")
    second = memory_gateway.submit("technical_indicators", {"close": [1, 2]}, "key-1")
    assert second.job_id == first.job_id

def test_resume_collects_ready_job_with_original_thread_id(fake_runtime):
    ResumeCoordinator(fake_runtime).resume_ready("v1:CUST1:conv-1")
    assert fake_runtime.resumed == [("v1:CUST1:conv-1", "job-1")]
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_quant_gateway.py tests/test_resume_coordinator.py -v`

Expected: FAIL because Celery adapters are absent.

- [ ] **Step 3: Implement worker separation and recovery**

Configure Celery with Redis DB `CELERY_REDIS_DB`, queue `finance.quant`, JSON serializers, `task_acks_late=True`, explicit soft/hard time limits and result expiry. Implement Celery tasks only for technical indicators, batch scoring/theme screening, backtest and replay. Tasks accept JSON payloads and return JSON-safe artifacts; they must not import or invoke LangGraph.

`QuantGateway` polls only within the request budget. Pending work writes `AsyncJobRef` and routes to a LangGraph interrupt carrying `awaiting_quant`. `ResumeCoordinator` is invoked by the async-status endpoint and optional periodic sweep; it verifies stored job ownership and status, then resumes the original graph with its persisted `thread_id`, `run_id` and `task_id`. A cancelled run revokes only queued tasks and ignores late successful results.

- [ ] **Step 4: Run gateway and domain regression tests**

Run: `pytest tests/test_quant_gateway.py tests/test_resume_coordinator.py tests/test_technical_indicators.py tests/test_research_backtest.py -v`

Expected: PASS using in-memory gateway; add a separately marked Redis/Celery integration test that is skipped unless `RUN_CELERY_INTEGRATION=1`.

- [ ] **Step 5: Commit async quant execution**

```bash
git add finance_agent/celery_app.py finance_agent/tasks finance_agent/orchestrator/quant.py finance_agent/orchestrator/resume.py finance_agent/orchestrator/domains/stock.py finance_agent/config.py pyproject.toml requirements.txt tests/test_quant_gateway.py tests/test_resume_coordinator.py
git commit -m "feat: offload quant work through celery"
```

### Task 9: 添加统一合规出口、响应投影与异步 API 状态

**Files:**

- Create: `finance_agent/orchestrator/compliance.py`
- Modify: `finance_agent/orchestrator/root_graph.py`
- Modify: `finance_agent/orchestrator/orchestrator.py`
- Modify: `finance_agent/api/routes.py`
- Modify: `finance_agent/api/schemas.py`
- Modify: `finance_agent/api/sse.py`
- Test: `tests/test_compliance_graph.py`
- Test: `tests/test_async_run_api.py`
- Test: `tests/test_response_projection_v2.py`

**Interfaces:**

- Produces `build_compliance_graph(policy, model)` and `ResponseProjector.project(state) -> dict[str, Any]`.
- Adds authenticated `GET /api/runs/{task_id}` which calls `ResumeCoordinator` before returning a safe status.

- [ ] **Step 1: Write failing compliance and projection tests**

```python
def test_compliance_rewrite_preserves_evidence_and_numbers():
    final = run_compliance(draft="保证收益 10%", evidence=[evidence("p/e", 12.5)])
    assert final.action == "rewritten"
    assert final.evidence == [evidence("p/e", 12.5)]
    assert "12.5" in final.response

def test_second_failed_compliance_review_blocks_output():
    assert run_compliance(draft="违规", policy=always_reject()).action == "blocked"

def test_processing_response_keeps_legacy_fields(client):
    payload = client.get("/api/runs/job-1", headers=auth()).json()
    assert payload["run_status"] == "processing"
    assert "response" in payload
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_compliance_graph.py tests/test_async_run_api.py tests/test_response_projection_v2.py -v`

Expected: FAIL because compliance is still embedded in Supervisor and async status does not exist.

- [ ] **Step 3: Implement the mandatory final subgraph**

Route conversation, single-domain and plan outputs through deterministic content rules, semantic review, one optional rewrite, recheck and block. Store reason code, rule version, controlled draft hash and final action in the audit record. Delete output-side compliance branching from `ManagerAgent.synthesize_response` once Root Graph is enabled.

`ResponseProjector` must preserve current response keys and add only `run_status`, `task_id`, `pending_task_ids` and safe warnings. SSE sends existing `stage`, `heartbeat`, `response` shapes plus `async_task` with task ID/status. The run-status endpoint must authorize the current customer before reading async state or resuming a graph.

- [ ] **Step 4: Run API and regression suite**

Run: `pytest tests/test_compliance_graph.py tests/test_async_run_api.py tests/test_response_projection_v2.py tests/test_runtime_controls.py tests/test_stream_and_product.py -v`

Expected: PASS.

- [ ] **Step 5: Commit compliance and API surface**

```bash
git add finance_agent/orchestrator/compliance.py finance_agent/orchestrator/root_graph.py finance_agent/orchestrator/orchestrator.py finance_agent/api/routes.py finance_agent/api/schemas.py finance_agent/api/sse.py tests/test_compliance_graph.py tests/test_async_run_api.py tests/test_response_projection_v2.py
git commit -m "feat: enforce compliance graph and async run status"
```

### Task 10: 删除旧专家编排、完成迁移开关与全量验收

**Files:**

- Modify: `finance_agent/orchestrator/orchestrator.py`
- Modify: `finance_agent/orchestrator/scheduler.py`
- Modify: `finance_agent/agents/__init__.py`
- Delete: `finance_agent/agents/supervisor.py`
- Delete: `finance_agent/agents/casual_chat.py`
- Delete: `finance_agent/agents/stock_analysis.py`
- Delete: `finance_agent/agents/market_insight.py`
- Delete: `finance_agent/agents/product_analysis.py`
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-09-14-langgraph-hybrid-orchestration-design.md`
- Test: `tests/test_legacy_agent_retirement.py`
- Test: `tests/test_orchestration_e2e_v2.py`

**Interfaces:**

- Produces a single production `AdvisorSystem` execution path based on Root Graph.
- Consumes all previous tasks.

- [ ] **Step 1: Write failing retirement and end-to-end tests**

```python
def test_production_graph_does_not_import_legacy_agent_classes():
    source = Path("finance_agent/orchestrator/orchestrator.py").read_text(encoding="utf-8")
    assert "StockAnalysisAgent" not in source
    assert "ProductAnalysisAgent" not in source
    assert "MarketInsightAgent" not in source

def test_composite_request_uses_plan_then_compliance(v2_system):
    result = v2_system.handle_message("分析贵州茅台并比较合适的基金产品", customer_id="CUST1")
    assert result["run_status"] in {"completed", "partial", "processing"}
    assert result["compliance_result"]["action"] in {"passed", "rewritten", "blocked"}
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_legacy_agent_retirement.py tests/test_orchestration_e2e_v2.py -v`

Expected: FAIL while legacy classes and feature-flag path remain.

- [ ] **Step 3: Remove legacy runtime path only after full v2 parity**

Set v2 as the only `AdvisorSystem` path, remove legacy scheduler usage and delete the five legacy Agent modules after their extracted deterministic helpers are imported by domain graphs. Update tests that constructed those classes to test graph nodes and public output instead. Update README environment variables, FAQ indexing command, Celery worker command, async status endpoint, resume behavior and composite `thread_id` semantics.

Do not delete `finance_agent/agents/base.py` until `rg -n "agents\.base|AgentProtocol|ProceduralAgent" finance_agent tests` has no production imports. If it has no imports, delete it and its empty package exports in the same commit.

- [ ] **Step 4: Run complete verification**

Run: `python -m compileall -q finance_agent`

Expected: exit code 0.

Run: `pytest -q`

Expected: PASS. If PostgreSQL/Redis/Celery integration tests are environment-gated, report their explicit skip condition and run them with configured services before production rollout.

- [ ] **Step 5: Commit retirement and documentation**

```bash
git add finance_agent README.md docs/superpowers/specs/2026-09-14-langgraph-hybrid-orchestration-design.md tests
git add -u finance_agent/agents
git commit -m "refactor: replace legacy agents with langgraph domains"
```

## Plan Self-Review

### Spec coverage

- 双模式、三个顶层领域、单领域 Domain ReAct 与复合 Plan-and-Execute：Tasks 4–7。
- ReAct 四轮、计划八任务/两次重规划、根图 32 步：Tasks 1、4、5、7。
- `user_id:session_id` checkpoint 隔离、旧键迁移和断点恢复：Tasks 1、2、5、8。
- 本地中文 embedding、pgvector 与三个平铺 FAQ 文件：Tasks 2、3。
- Celery CPU 队列、Redis 隔离、同步预算等待和恢复：Task 8。
- 所有输出统一合规：Task 9。
- 删除三个专业 Agent 类和旧编排：Task 10。
- 兼容 API/SSE、无静默回退、全量测试：Tasks 5、9、10。

### Placeholder scan

本计划没有未决项目、模糊错误处理表述或未定义接口引用。所有新增接口在 Task 1 或其所属任务中定义，后续任务按该名称引用。

### Type consistency

`BusinessDomain`、`RunBudgets`、`PlanTask`、`DomainOutcome`、`AsyncJobRef` 在 Task 1 建立；FAQ、ReAct、Root Graph、Domain Graph、Plan-and-Execute、Celery 与合规任务均以这些契约作为跨模块接口。`thread_id` 始终由 `build_thread_id(customer_id, conversation_id)` 创建，领域并发仅传递 `task_id`，不改写线程键。
