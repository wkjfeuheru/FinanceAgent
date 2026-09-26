# Persistence and data adapters

PostgreSQL adapters are owned by `finance_agent/infrastructure/persistence/postgres/`.
The canonical SQL history lives in the repository-root `migrations/` directory and is
loaded by `finance_agent/infrastructure/persistence/postgres/schema.py` and applied
through `finance_agent/cli/migrate.py` / `finance_agent/infrastructure/persistence/postgres/migrations.py`.

## Components

- `transaction.py` owns the shared DB-API connection and transaction lifecycle.
- `schema.py` loads ordered SQL scripts from `migrations/`; `migrations.py` owns the
  canonical application order.
- `auth_store.py`, `business_store.py`, `portfolio_store.py`, and `product_store.py`
  implement infrastructure adapters for their respective persistence ports.
- `runtime_repository.py`, `audit_repository.py`, `async_run_repository.py`, and
  `research_repository.py` persist orchestration and research records.
- FAQ persistence is implemented by `faq_repository.py`; the port and its data
  contracts are defined by `finance_agent/domains/faq/`.
- `finance_agent/application/async_recovery.py` coordinates async-job recovery;
  checkpoint keys and runtime state live under `finance_agent/orchestration/runtime/`.

Connection settings and the connection factory are provided by
`finance_agent/infrastructure/settings.py`.

## Migration conventions

1. Treat applied historical migrations as immutable; append a numbered script for a
   schema change.
2. Keep ordering centralized in `migrations.py`. FAQ pgvector setup remains isolated
   from the base schema and is initialized by the FAQ adapter when needed.
3. Use idempotent DDL. `CREATE TABLE IF NOT EXISTS` does not add columns to existing
   tables, so column changes need `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`.
4. Reuse `transaction.py` for connection lifetime, commit, and rollback behavior;
   adapters should not implement their own transaction bodies.

## Dependency direction

Domain packages define persistence ports and contracts. Infrastructure implements
those ports using PostgreSQL and external drivers; domain rules do not depend on SQL,
connection factories, or infrastructure adapters.

## Checkpoint 兼容性与部署（根图拓扑变更时必读）

LangGraph 的检查点按 `thread_id` 存储，`thread_id` 的主语义是
`user_id:session_id`（`orchestration/runtime/thread_key.py`，当前版本前缀 `v1`）。
一个检查点里的 `next` 指向**上一版图里的节点名**：根图拓扑（节点集合、状态
schema、边）发生不兼容变更后，旧快照无法在新图上恢复，恢复时会直接报错。

因此**重写根图拓扑的那一次部署必须显式放弃旧检查点**：

1. 停服（避免部署窗口内仍有在途运行写检查点）；
2. 清空 LangGraph 的四张表：`checkpoints`、`checkpoint_blobs`、
   `checkpoint_writes`、`checkpoint_migrations`；
3. 部署新版本，再校验（挂起中的缺参追问与在途运行会被放弃，用户重新提问即可）。

**对话历史与用户画像不受影响**：它们按 `customer_id` / `conversation_id` 存在业务表
（`finance.conversations` / `finance.user_profiles`）里，与检查点无关；被放弃的只有
"图状态"这一层。

线程键版本（`_THREAD_KEY_VERSION`）不是替代方案：换键同样会孤立旧检查点，而且会让
"同一会话的两套快照"长期留在库里。清表是更干净的一次性动作。

