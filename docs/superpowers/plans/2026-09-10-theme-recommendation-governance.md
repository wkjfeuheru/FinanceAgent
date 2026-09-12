# 主题推荐治理实施计划

> **状态：已实施完成（2026-09 复核）。** 复选框未回填、保持原样作为历史记录；
> 实际进度以 git 历史为准（`6631fd6`、`6e18fc2`、`57d5e0f` 等）。全部任务 1–5
> 的产物已存在并入库：`sql/004_research_governance.sql`、`research/theme_models.py`、
> `theme_repository.py`、`theme_discovery.py`、`screener.py`、`refresh.py`、`backtest.py`、
> admin 审核路由与 `ThemeReviewQueue.vue`，及对应测试。主题注册表（名称→theme_id）
> 于 2026-09-12 另立（`sql/005_theme_registry.sql`），见
> `2026-09-12-stock-analysis-routing-fixes.md`。

> **供智能代理执行：** 必须使用子技能 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，逐项实施本计划。所有步骤使用复选框（`- [ ]`）跟踪。

**目标：** 在确定性研究流水线之上，构建可审计的 PostgreSQL 主题候选池、Provider 驱动的候选发现、管理员审核、确定性主题筛选和研究运行记录。

**架构：** 外部 Provider 仅创建带证据的不可变待审核线索；只有经管理员批准且尚未过期的成员关系才会生效。每日刷新为有效成员计算可复用特征；在线筛选刷新最新报价后，按确定性规则返回分散化候选。待审核线索只以独立的研究提示展示。

**技术栈：** Python 3.10+、PostgreSQL/psycopg、FastAPI、Vue 3/TypeScript、Pydantic v2、pytest。

## 全局约束

- 本计划依赖 `2026-09-10-deterministic-stock-analysis.md`。
- 生产环境由 Provider 驱动候选发现；不新增 CSV/Excel 导入路径。
- 公司官方披露、交易所披露和官网是最终证据；授权分类服务用于发现线索；新闻、网页、LLM 只能生成线索。
- 成员状态为 `pending`、`active`、`expired`、`rejected`。待审核记录 30 天后过期；有效记录在证据到期前 30 天进入复核，证据到期后不得继续参与推荐。
- 只有有效记录可参与评分、排序和行动标签。待审核记录必须以 `待核验研究线索` 展示，不得带评分或行动结论。
- 正式主题推荐至少需要 5 个有效候选，返回 3–5 只股票；同一细分行业最多出现 2 只。
- 未同时提供风险承受能力和持有期限时，只能输出非个性化 `research_candidate`。

---

## 文件结构

- 新建：`sql/004_research_governance.sql`——成员关系、证据、审核、特征和研究运行表。
- 修改：`finance_agent/data/postgres_schema.py`——加载 004 SQL 迁移。
- 新建：`finance_agent/research/theme_models.py`、`theme_repository.py`、`theme_discovery.py`、`screener.py`、`refresh.py`、`backtest.py`。
- 修改：`finance_agent/research/pipeline.py`、`finance_agent/data/postgres_repository.py`、`finance_agent/api/schemas.py`、`finance_agent/api/routes.py`、`README.md`。
- 新建：`frontend/src/components/ThemeReviewQueue.vue`。
- 修改：`frontend/src/api/chat.ts`、`frontend/src/types/index.ts`、`frontend/src/components/MessageList.vue`。
- 新建测试：`tests/test_theme_repository.py`、`tests/test_theme_discovery.py`、`tests/test_theme_screener.py`、`tests/test_research_refresh.py`、`tests/test_theme_admin_routes.py`、`tests/test_research_backtest.py`。

### 任务 1：PostgreSQL 主题候选池与证据仓储

**文件：**

- 新建：`sql/004_research_governance.sql`
- 修改：`finance_agent/data/postgres_schema.py`
- 新建：`finance_agent/research/theme_models.py`
- 新建：`finance_agent/research/theme_repository.py`
- 测试：`tests/test_theme_repository.py`

**接口：**

- `ThemeRepository.ingest_lead(lead: ThemeLead) -> ThemeLead` 按主题、股票、来源和证据哈希幂等。
- `ThemeRepository.review_lead(lead_id, *, reviewer_id, decision, expires_at, note) -> ThemeMembership` 只允许转换待审核记录。
- `ThemeRepository.active_members(theme_id, as_of) -> list[ThemeMembership]` 只返回仍有效的生效成员。

- [ ] **步骤 1：编写待审核记录隔离失败测试**

~~~python
def test_pending_lead_is_not_active(repository):
    repository.ingest_lead(ai_lead(stock_code="600519"))
    assert repository.active_members("ai_compute", as_of=utcnow()) == []
    assert len(repository.pending_leads("ai_compute")) == 1
~~~

- [ ] **步骤 2：运行测试并确认失败**

运行：`pytest tests/test_theme_repository.py::test_pending_lead_is_not_active -v`

预期：失败，因为仓储尚不存在。

- [ ] **步骤 3：创建治理迁移**

~~~sql
CREATE TABLE IF NOT EXISTS finance.theme_memberships (
    membership_id uuid PRIMARY KEY,
    theme_id varchar(128) NOT NULL,
    stock_code varchar(16) NOT NULL,
    industry varchar(128) NOT NULL DEFAULT '',
    status varchar(16) NOT NULL CHECK (status IN ('pending','active','expired','rejected')),
    evidence_expires_at timestamptz NOT NULL,
    activated_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_theme_membership_current
ON finance.theme_memberships(theme_id, stock_code)
WHERE status IN ('pending','active');
~~~

新增 `theme_evidence`、`theme_reviews`、`research_feature_snapshots`、`research_runs`、`research_results`。证据表保存来源名称/类别/URI/摘录/哈希/发现时间；审核表保存审核人、决定、备注和时间；研究表保存请求、快照清单、规则版本、评分、行动结论和事实 ID。

- [ ] **步骤 4：实现事务性过期和审核方法**

~~~python
def expire_stale_records(self, as_of: datetime) -> int:
    return self._execute_count(
        "UPDATE finance.theme_memberships SET status = 'expired', updated_at = %s "
        "WHERE (status = 'pending' AND created_at < %s - interval '30 days') "
        "OR (status = 'active' AND evidence_expires_at <= %s)",
        (as_of, as_of, as_of),
    )
~~~

- [ ] **步骤 5：添加状态转换测试**

~~~python
def test_only_review_activates_pending_lead(repository):
    lead = repository.ingest_lead(ai_lead())
    member = repository.review_lead(lead.id, reviewer_id="ADMIN1", decision="approve", expires_at=future, note="公告核验")
    assert member.status == "active"


def test_expired_member_is_excluded(repository):
    repository.seed_active(ai_lead(), expires_at=past)
    repository.expire_stale_records(utcnow())
    assert repository.active_members("ai_compute", utcnow()) == []
~~~

- [ ] **步骤 6：验证并提交**

运行：`pytest tests/test_theme_repository.py tests/test_postgres_schema.py -v`

预期：全部通过。

~~~bash
git add sql/004_research_governance.sql finance_agent/data/postgres_schema.py finance_agent/research tests
git commit -m "feat: add theme universe governance schema"
~~~

### 任务 2：Provider 驱动发现并写入待审核线索

**文件：**

- 新建：`finance_agent/research/theme_discovery.py`
- 修改：`finance_agent/config.py`
- 测试：`tests/test_theme_discovery.py`

**接口：**

- `ThemeDiscoveryProvider.discover(theme_id: str) -> Iterable[ThemeLead]` 绝不返回生效成员。
- `ThemeDiscoveryService.sync(theme_id) -> DiscoverySummary` 只校验并写入待审核线索。

- [ ] **步骤 1：编写发现隔离失败测试**

~~~python
def test_external_discovery_creates_pending_only():
    summary = service.sync("ai_compute")
    assert summary.inserted_pending == 1
    assert repository.active_members("ai_compute", utcnow()) == []
~~~

- [ ] **步骤 2：运行测试并确认失败**

运行：`pytest tests/test_theme_discovery.py::test_external_discovery_creates_pending_only -v`

预期：失败，因为发现服务尚不存在。

- [ ] **步骤 3：实现标准化线索校验**

~~~python
@dataclass(frozen=True)
class ThemeLead:
    theme_id: str
    stock_code: str
    industry: str
    source_name: str
    source_class: Literal["official", "licensed_classification", "public_lead"]
    source_uri: str
    evidence_excerpt: str
    evidence_hash: str
    discovered_at: datetime
~~~

拒绝无效代码、缺失来源 URI、缺失证据摘录和未支持来源类别。允许 `public_lead` 写入待审核区，但必须在审核界面中明确标记。

- [ ] **步骤 4：实现可配置 Provider 适配器**

创建由配置选择 HTTP/MCP 客户端的 `ConfiguredThemeDiscoveryProvider`，将供应商响应转换为 `ThemeLead`，凭据仅保存在环境配置中。适配器不得赋予评分、行动标签或生效状态。

- [ ] **步骤 5：添加格式错误和重复线索测试**

~~~python
def test_same_evidence_hash_is_idempotent():
    service.sync("ai_compute")
    service.sync("ai_compute")
    assert repository.pending_count("ai_compute") == 1


def test_missing_source_uri_is_rejected_before_storage():
    assert service.sync("bad_theme").rejected == 1
~~~

- [ ] **步骤 6：验证并提交**

运行：`pytest tests/test_theme_discovery.py -v`

预期：全部通过。

~~~bash
git add finance_agent/research/theme_discovery.py finance_agent/config.py tests/test_theme_discovery.py
git commit -m "feat: ingest external theme discovery leads"
~~~

### 任务 3：仅有效成员的筛选、分散化与研究记录

**文件：**

- 新建：`finance_agent/research/screener.py`
- 修改：`finance_agent/research/pipeline.py`
- 修改：`finance_agent/data/postgres_repository.py`
- 测试：`tests/test_theme_screener.py`

**接口：**

- `ThemeScreener.screen(request, profile) -> ThemeScreeningResult` 分离有效候选排名与待审核线索。
- `ResearchRunRepository.save(result, *, run_id, customer_id, conversation_id) -> str` 保存可重放研究运行。
- 有效成员少于 5 只时，筛选器返回 `insufficient_active_coverage`。

- [ ] **步骤 1：编写覆盖数和分散化失败测试**

~~~python
def test_screener_requires_five_active_members():
    result = screener.screen(theme_request("ai_compute"), profile={})
    assert result.status == "insufficient_active_coverage"
    assert result.ranked_candidates == []


def test_screener_caps_fine_industry_at_two():
    result = populated_screener.screen(theme_request("ai_compute"), profiled_user)
    assert max(count_by_industry(result.ranked_candidates).values()) <= 2
~~~

- [ ] **步骤 2：运行测试并确认失败**

运行：`pytest tests/test_theme_screener.py -v`

预期：失败，因为筛选器尚不存在。

- [ ] **步骤 3：实现仅有效成员参与的排序**

~~~python
active = self._themes.active_members(request.theme_id, as_of=now)
if len(active) < 5:
    return ThemeScreeningResult.insufficient_coverage(
        pending_leads=self._themes.pending_leads(request.theme_id),
    )
~~~

为每个有效成员获取当前报价/质量快照，调用第一阶段规则引擎，按确定性分数排序，执行风险门禁，同一行业限制两只，返回 3–5 只候选。待审核线索不能进入候选列表，也不能含行动或评分字段。

- [ ] **步骤 4：持久化可重放结果**

写入 `finance.research_runs`，包括请求 JSON、画像完整度、快照清单、规则版本、状态，以及与 `agent_runs.run_id` 的关联。写入 `finance.research_results`，包括候选行动、分项评分、证据 ID 和排除原因。

- [ ] **步骤 5：添加非个性化响应测试**

~~~python
def test_missing_profile_never_claims_personal_suitability():
    result = populated_screener.screen(theme_request("ai_compute"), profile={})
    assert result.personalization_status == "research_candidate"
    assert all("适合你" not in item.summary for item in result.ranked_candidates)
~~~

- [ ] **步骤 6：验证并提交**

运行：`pytest tests/test_theme_screener.py tests/test_postgres_repository.py -v`

预期：全部通过。

~~~bash
git add finance_agent/research/screener.py finance_agent/research/pipeline.py finance_agent/data/postgres_repository.py tests
git commit -m "feat: add deterministic theme screening"
~~~

### 任务 4：每日刷新和防未来函数回测门槛

**文件：**

- 新建：`finance_agent/research/refresh.py`
- 新建：`finance_agent/research/backtest.py`
- 修改：`finance_agent/config.py`
- 修改：`README.md`
- 测试：`tests/test_research_refresh.py`
- 测试：`tests/test_research_backtest.py`

**接口：**

- `refresh_active_theme_features(as_of: datetime | None = None) -> RefreshSummary` 仅处理有效记录。
- `run_walk_forward_backtest(theme_id, start, end, rule_version) -> BacktestReport` 只使用再平衡日当日或之前可得的快照。

- [ ] **步骤 1：编写刷新和未来数据泄漏失败测试**

~~~python
def test_refresh_skips_pending_and_expired_members():
    summary = refresher.run(as_of=utcnow())
    assert summary.refreshed_codes == ["600519"]
    assert summary.skipped_pending == ["600036"]
    assert summary.skipped_expired == ["000001"]


def test_backtest_never_uses_future_snapshot():
    report = run_walk_forward_backtest("ai_compute", date(2025, 1, 1), date(2025, 3, 31), "research_rules/v1")
    assert report.used_snapshot_dates[0] <= report.rebalance_dates[0]
~~~

- [ ] **步骤 2：运行测试并确认失败**

运行：`pytest tests/test_research_refresh.py tests/test_research_backtest.py -v`

预期：失败，因为对应模块尚不存在。

- [ ] **步骤 3：实现刷新命令**

为每个有效成员构建确定性快照和评估结果，并按股票代码、数据 `as_of` 和规则版本写入特征快照。失败原因必须记录，但不能写入占位分数。以下命令输出 JSON 汇总：

~~~bash
python -m finance_agent.research.refresh
~~~

在 README 中记录每日收盘后一次的调度方式。

- [ ] **步骤 4：实现滚动前推回测指标**

每个再平衡日只加载该日或之前的特征快照，再计算后续已实现结果。输出命中率、最大回撤、换手率、行业集中度和数据缺失率。报告关联规则版本，并具有 `experimental`、`default`、`rejected` 发布状态。

- [ ] **步骤 5：验证并提交**

运行：`pytest tests/test_research_refresh.py tests/test_research_backtest.py -v`

预期：全部通过。

~~~bash
git add finance_agent/research/refresh.py finance_agent/research/backtest.py finance_agent/config.py README.md tests
git commit -m "feat: add research refresh and backtest gate"
~~~

### 任务 5：管理员审核 API 与结果界面

**文件：**

- 修改：`finance_agent/api/schemas.py`
- 修改：`finance_agent/api/routes.py`
- 新建：`frontend/src/components/ThemeReviewQueue.vue`
- 修改：`frontend/src/api/chat.ts`、`frontend/src/types/index.ts`、`frontend/src/components/MessageList.vue`
- 测试：`tests/test_theme_admin_routes.py`

**接口：**

- `GET /api/admin/themes/{theme_id}/leads` 仅向管理员列出待审核线索。
- `POST /api/admin/theme-leads/{lead_id}/review` 接收 `approve` 或 `reject`、证据到期时间和备注。
- 聊天响应展示有效候选的证据摘要；待审核线索必须与候选结果结构化隔离。

- [ ] **步骤 1：编写路由鉴权失败测试**

~~~python
def test_non_admin_cannot_list_pending_leads(client, user_token):
    response = client.get("/api/admin/themes/ai_compute/leads", headers=auth(user_token))
    assert response.status_code == 403


def test_admin_can_approve_pending_lead(client, admin_token, pending_lead):
    response = client.post(
        f"/api/admin/theme-leads/{pending_lead.id}/review",
        headers=auth(admin_token),
        json={"decision": "approve", "evidence_expires_at": "2027-09-10T00:00:00Z", "note": "公告核验"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "active"
~~~

- [ ] **步骤 2：运行测试并确认失败**

运行：`pytest tests/test_theme_admin_routes.py -v`

预期：在路由创建前返回 404。

- [ ] **步骤 3：通过既有管理员鉴权实现审核 API**

使用 `_require_customer_id` 和 `ADMIN_CUSTOMER_IDS`；未认证和非管理员分别返回 401/403。校验封闭的审核枚举。审核 API 可变更状态、到期时间和备注，但不得替换股票代码或原始证据。

- [ ] **步骤 4：渲染结构化研究结果**

在后端和 TypeScript `ChatResponse` 中增加可选 `analysis_results`。在 `MessageList.vue` 中显示有效候选的行动、规则版本、数据日期、分项评分和证据来源徽标。把待审核线索放入独立的 `待核验研究线索` 区域，不显示评分和行动。

- [ ] **步骤 5：新增审核组件并验证构建**

`ThemeReviewQueue.vue` 显示来源 URI、摘录、到期日，支持通过/拒绝；审核成功后从待审核列表移除对应记录。必须复用既有认证客户端，不得向非管理员展示。

运行：`pytest tests/test_theme_admin_routes.py -v`

预期：全部通过。

运行：`npm --prefix frontend run build`

预期：通过。

- [ ] **步骤 6：提交**

~~~bash
git add finance_agent/api frontend/src tests/test_theme_admin_routes.py
git commit -m "feat: add governed theme review and research rendering"
~~~

## 自检

- 覆盖：PostgreSQL 主题存储、直接外部冷启动发现、人工审核、生命周期过期、仅有效成员筛选、五只覆盖门槛、画像安全输出、预计算、研究审计、审核 API/UI、分散化和时间安全发布验证均已映射到任务 1–5。
- 类型一致性：先定义 `ThemeLead`，再供仓储/发现使用；先定义 `ThemeMembership`，再供筛选/刷新使用；先定义筛选输出，再供 API/UI 使用。
- 自动化测试使用 Fake Provider、固定快照和 Fake Repository，不依赖供应商服务。

## 执行交接

计划保存在 `docs/superpowers/plans/2026-09-10-theme-recommendation-governance.md`。

执行方式：

1. **子代理驱动（推荐）**——每个任务使用新的子代理，任务间进行审核。
2. **当前会话执行**——使用 `executing-plans` 分阶段执行，并设置审核检查点。

