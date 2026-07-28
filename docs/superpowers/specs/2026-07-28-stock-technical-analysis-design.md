### 3.2 实施中额外修改的文件（偏离计划）

- `finance_agent/core/memory.py` — Bug fix: 用户画像读写从 checkpoint 迁移到 `finance_agent.db` 的 SQLite 持久化，恢复丢失的历史数据；删除废弃的 `_profile_thread_id` 辅助函数
- `finance_agent/agents/fundamental_analysis.py` — 已删除，被 `stock_analysis.py` 替代
- `tests/` — 将 `fundamental_agent` 引用更新为 `stock_agent`；将 `fundamental_analysis`/`fundamental_entries` 字段更新为 `stock_analysis`/`stock_analysis_entries`
- `README.md` — 新增技术面分析功能描述，更新工作流图

### 3.3 最终提交统计

- **32 commits** on main, **69/69 tests** passing, working tree clean
- 新增文件: `technical_indicators.py` (520行), `stock_analysis.py` (562行)
- 修改文件: `orchestrator.py`, `__init__.py` (agents+tools), `memory.py`, `config.py`, `README.md`, test files
- 删除文件: `fundamental_analysis.py`
- 不变文件: `supervisor.py`, `data_fetch.py`, `shared_state.py`

## 四、架构设计