# Finance Agent

基于 LangGraph 多 Agent 协作的智能投顾助手。系统通过自然语言收集用户投资需求，完成用户画像提取、股票识别、行情与财务数据获取、基本面分析、技术分析、市场洞察和合规审查，并提供 Vue 3 Web 界面及 FastAPI 接口。

## 功能特性

- 多 Agent 工作流：由 Supervisor 规划并协调各专业 Agent。
- A 股数据：默认按 `DATA_PROVIDER_ORDER` 在 AKShare / Tushare MCP / BaoStock 之间按方法降级，获取股票信息、最近交易日行情、历史 K 线和财务指标。
- 可选数据源：配置 `TUSHARE_MCP_URL` 后启用 Tushare MCP 作为其中一路（需 ≥2000 积分才能提供股息率）。
- 智能选股：可选接入联网搜索，辅助识别行业、主题和股票名称。
- 基本面与技术面分析：支持财务指标及 MACD、KDJ、RSI、BOLL、MA、WR 等指标。
- 市场洞察：大盘概览、市场情绪、资金面与政策事件影响，只回答市场整体问题，不输出个股结论。
- 合规审查：对最终回答执行敏感内容和投资风险检查。输入侧区分“问规则”与“求操作”：合规的知识咨询（如“什么是操纵市场？”）放行并走 FAQ，求助执行类请求（如“帮我操纵股价”）拦截；无法判定时默认拦截。引用 FAQ 原文的回答只审计不改写，避免删改风险词汇导致语句失真。
- 流式对话：支持基于 SSE 的实时响应。
- 用户系统：支持注册、登录、Bearer Token 认证、会话管理和账户注销。
- 模拟交易：商品货架（基金产品按最新净值展示，含风险等级与费率）、按金额/份额申购、持仓按最新净值估值、部分或全部赎回、一键清仓、账户数据面板（总资产/可用资金/持仓市值/累计与已实现盈亏）与虚拟资金充值。单一服务层同时支撑 REST 接口与对话问答，因此两个入口的口径必然一致。**模拟盘，不对接券商，不构成投资建议。**
- 多层记忆：Redis 保存运行时记忆，PostgreSQL 保存认证、业务数据和 LangGraph checkpoint。
- 强制登录：匿名访问已关闭。聊天、画像、历史记录、会话管理、账户操作和模拟交易都必须使用有效登录令牌。

## 工作流程

```text
用户请求
   |
   v
用户认证
   |
   v
Supervisor Graph（领域分类与路由）
   |
   +--> 业务领域（单领域或多领域并行扇出，同一路径）
   |      Stock Research（基本面 + 技术面）
   |      Market Insight（大盘/情绪/资金面/政策事件）
   |      Product Research（产品解读与适配度）
   |      Account Portfolio（自有账户与持仓，只读）
   +--> 无业务领域：Conversation（FAQ 检索 + 受约束叙述）
   |
   v
Compliance（统一合规出口）
   |
   v
最终回答
```

Supervisor Graph 会按意图选择领域，并非每次请求都执行完整流程。**账户领域是只读的**：它只调用
账户与持仓查询，命中"买入/卖出/清仓/充值"时返回固定引导文案，不做任何资金操作——交易必须
在「商品」「持仓」「账户」页面由用户显式完成。多标的请求（选股推荐、
股票比较）会按标的并行取数并逐只给出独立结论。`Market Insight` 只回答市场整体问题，不输出
个股结论或推荐，支持四种模式：大盘概览（主要指数 + 市场宽度 + 成交额 + 区间涨跌）、市场情绪（涨跌家数/活跃度）、
资金面（两市融资融券日频含日环比 + 北向持股市值季度参考）、政策事件影响（政策新闻筛选 + 定性影响解读）。
指数数据走 AKShare 新浪源、宽度走乐咕、融资融券与北向走东财/交易所，政策新闻走新浪全球快讯（央视新闻联播作政策补充）。
**北向逐日净买额自 2024-08 起因监管披露调整停止披露**（历史序列亦停更），因此资金面改用仍在日频
披露的两市融资融券作为主指标，北向仅保留季度披露的持股市值并标注滞后。政策事件影响模式的取数为
确定性关键词筛选，影响解读由 LLM 基于筛选出的事件生成（失败时回退纯事件清单，不伪造）。

## 技术栈

### 后端

- Python 3.10+
- FastAPI / Uvicorn
- LangChain / LangGraph
- DeepSeek
- Tushare MCP
- Redis
- PostgreSQL
- Celery
- pandas / NumPy

### 前端

- Vue 3
- TypeScript
- Vite
- Vue Router
- Element Plus
- Axios

## 项目结构

```text
FinanceAgent/
├── finance_agent/
│   ├── api/                 # FastAPI 应用、路由和请求/响应模型
│   ├── application/         # Advisor 用例、回合协调、持久化与恢复
│   ├── cli/                 # 管理员、FAQ、诊断和研究回放命令
│   ├── domains/             # FAQ、组合、产品与股票研究领域
│   ├── infrastructure/     # PostgreSQL、Redis、LLM、行情与后台任务
│   ├── orchestration/       # 专家、路由、工作流、记忆与运行时
│   ├── safety/              # 输入与输出安全策略
│   ├── shared/              # 跨层契约、序列化和标识符
│   ├── bootstrap.py         # 应用依赖装配
│   └── main.py              # 公开 ASGI 入口
├── frontend/src/            # Vue 应用、共享 API client 与 feature slices
├── migrations/              # PostgreSQL 编号迁移（001–014）
├── evals/                   # 评测场景、运行器与基线
├── tests/                   # architecture / unit / integration / contract / e2e
├── scripts/                 # 本地启动与评测封装脚本
├── docs/                    # 架构、FAQ、参考和运维文档
├── deploy/                  # Docker/Nginx 部署资产
├── docker-compose.yml
├── Dockerfile
├── Dockerfile.web
├── pyproject.toml
├── requirements.txt
└── requirements.lock
```

## 环境要求

- Python 3.10 或更高版本
- Node.js 18 或更高版本
- Redis 服务
- 有效的 DeepSeek API Key
- PostgreSQL（认证、业务、checkpoint；预发镜像使用带 pgvector 的 Postgres 16）
- 生产/预发另需 Docker Compose

## 快速开始

### 1. 创建虚拟环境

```bash
git clone <repository-url>
cd FinanceAgent
python -m venv .venv
```

Windows PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
```

Linux / macOS：

```bash
source .venv/bin/activate
```

### 2. 安装后端依赖

推荐以可编辑模式安装：

```bash
pip install -e .
```

如果不使用可编辑安装，也可以直接安装依赖文件：

```bash
pip install -r requirements.txt
```

Docker 镜像按 `requirements.lock` 安装，避免每次构建漂版本。本地开发仍可用上面的下限约束。

安装开发和测试依赖：

```bash
pip install -e ".[dev]"
```

如需本地股票数据源（AKShare / BaoStock）：

```bash
pip install akshare baostock
```

> **务必用项目 `.venv` 运行后端。** 若机器上同时存在多个 Python（例如 Anaconda 与官方
> Python），只有装了依赖的那个解释器才能跑通完整链路；FAQ 检索依赖
> `sentence-transformers`（及其 `torch`/`scikit-learn`），缺失时知识类问答会退化为
> 「暂时无法执行该操作。」。用 `.venv/Scripts/python.exe -m uvicorn ...`（Windows）或
> `python -m uvicorn ...`（已激活 venv）启动可避免选错解释器。

### 3. 配置环境变量

`DEEPSEEK_API_KEY` 必须设置为操作系统环境变量。程序会在读取该密钥后加载 `.env`，但不会使用 `.env` 覆盖 DeepSeek 密钥。

Windows PowerShell：

```powershell
$env:DEEPSEEK_API_KEY="your-deepseek-api-key"
```

Linux / macOS：

```bash
export DEEPSEEK_API_KEY="your-deepseek-api-key"
```

在项目根目录创建 `.env`，示例配置如下：

```dotenv
# Redis
REDIS_URL=redis://localhost:6379/0
REDIS_MEMORY_TTL_SECONDS=3600

# PostgreSQL（必需；认证、业务、产品库和 checkpoint 共用）
POSTGRES_DSN=postgresql://postgres:password@localhost:5432/advisor
# 或使用以下组件配置：
# POSTGRES_HOST=localhost
# POSTGRES_PORT=5432
# POSTGRES_USER=postgres
# POSTGRES_PASSWORD=your-password
# POSTGRES_DB=advisor
POSTGRES_CONNECT_TIMEOUT=10
# checkpoint 连接池容量：不同会话可并发执行，每个 superstep 都会写 checkpoint。
# 上限过小会让并发会话在池上排队，因此显式放开（默认 4/16）。
POSTGRES_POOL_MIN_SIZE=4
POSTGRES_POOL_MAX_SIZE=16
POSTGRES_POOL_TIMEOUT=30

# 管理员 customer_id 白名单，多个值用逗号分隔；与库内 is_admin 取并集。
# 日常授权请用 finance_agent.cli.bootstrap_admin，这里留空即可。
# ADMIN_CUSTOMER_IDS=CUST000001,CUST000002

# 运行环境：production 时关闭 /docs 与 OpenAPI。
# APP_ENV=production
# 浏览器跨域来源（逗号分隔）。生产必须改成实际上线的前端源。
# 经本仓库 Nginx 同源反代时留空即可。
# CORS_ALLOW_ORIGINS=https://your-frontend.example
# 仅当 API 在反代之后时开启，登录限流才信任 X-Forwarded-For。
# TRUST_PROXY=true
# 本地默认 127.0.0.1；容器内必须 0.0.0.0。
# UVICORN_HOST=127.0.0.1

# Tushare MCP 数据源
# TUSHARE_MCP_URL=https://your-tushare-mcp-endpoint?token=your-token
TUSHARE_MCP_TIMEOUT=30

# 本地股票数据源：按顺序「按方法」降级
DATA_PROVIDER_ORDER=akshare,tushare_mcp,baostock
AKSHARE_ENABLED=true
BAOSTOCK_ENABLED=true
# Tushare 必须先配置 TUSHARE_MCP_URL 才会启用
TUSHARE_ENABLED=true

# 行情与估值本地缓存：默认锚定仓库根目录的 .cache/quotes，自定义请用绝对路径
# QUOTE_CACHE_DIR=/abs/path/to/quotes
# TTL 设为 0 表示关闭缓存
QUOTE_CACHE_TTL_SECONDS=3600

# 模拟交易限额：充值单笔上限与单笔申购下限（元）
PORTFOLIO_MAX_DEPOSIT_AMOUNT=10000000
PORTFOLIO_MIN_ORDER_AMOUNT=100

# 模型和工作流参数
INTENT_MODEL_PROVIDER=qwen
INTENT_MODEL=qwen-turbo
# Qwen 兼容 OpenAI Chat Completions 的 endpoint 和 API key
INTENT_MODEL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
INTENT_MODEL_API_KEY=your-qwen-api-key
INTENT_MODEL_TIMEOUT=5
INTENT_MODEL_MAX_RETRIES=2
INTENT_MODEL_MAX_TOKENS=512
INTENT_MODEL_DEADLINE=15
# 降级链：主模型不可用（超时/欠费/协议错）时自动回退备用模型，避免单一 provider
# 故障打断全部分类与路由。一般不填 API key（自动继承 DEEPSEEK_API_KEY）。
INTENT_FALLBACK_MODEL=deepseek-chat
INTENT_FALLBACK_BASE_URL=https://api.deepseek.com/v1/chat/completions
# INTENT_FALLBACK_API_KEY=
INTENT_FALLBACK_TIMEOUT=20
INTENT_FALLBACK_DEADLINE=25
DEEPSEEK_INTENT_MODEL=deepseek-chat
DEEPSEEK_INTENT_TIMEOUT=30
DEEPSEEK_INTENT_MAX_RETRIES=1
LLM_REQUEST_TIMEOUT=45
LLM_MAX_RETRIES=1
FINAL_SYNTHESIS_TIMEOUT=20
POLICY_NEWS_MAX_DAYS=3
POLICY_NEWS_MAX_ITEMS=50
PRODUCT_ANALYSIS_TEMPERATURE=0.2

# 混合 LangGraph 编排预算（单一执行路径：Supervisor Graph）
# 这些变量是 RunBudgets 的唯一数值源，经 Pydantic 校验后注入会话 ReAct、
# 单轮扇出的领域数、缺参追问次数、合规改写与图递归上限
# （上限为全局硬天花板，见 orchestration/budgets.py）。
ORCHESTRATION_REACT_STEPS=4
ORCHESTRATION_MAX_DOMAINS=4
ORCHESTRATION_CLARIFY_ROUNDS=2
ORCHESTRATION_COMPLIANCE_REWRITES=1
ORCHESTRATION_GRAPH_STEPS=32
# 端到端墙钟上限：步数上限只约束"走了多少步"，管不住"某一步卡多久"。
# TURN_DEADLINE 是图内强制的**整轮**执行上限（单领域与多领域共用），
# TURN_TIMEOUT 是 API/SSE 层的等待上限；两者必须满足 TIMEOUT >= DEADLINE，
# 否则用户会先看到超时而执行线程仍在跑（构造时校验）。
ORCHESTRATION_TURN_TIMEOUT=180
ORCHESTRATION_TURN_DEADLINE=120

# 数据源守门：akshare/baostock 内部多数请求不设 socket 超时，
# 由 ProviderManager 在调用边界强制超时，并熔断连续失败的源。
DATA_PROVIDER_TIMEOUT=20
DATA_PROVIDER_FAILURE_THRESHOLD=3
DATA_PROVIDER_COOLDOWN=60

# Celery 量化计算：独立 Redis DB + 专用队列
CELERY_REDIS_DB=1
CELERY_QUANT_QUEUE=finance.quant
CELERY_TASK_SOFT_TIME_LIMIT=60
CELERY_TASK_HARD_TIME_LIMIT=120
CELERY_RESULT_EXPIRES=3600

# 本地 FAQ 中文 embedding（默认 CPU，不在启动时联网下载）
FAQ_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
FAQ_EMBEDDING_DEVICE=cpu
FAQ_EMBEDDING_MODEL_CACHE_DIR=.cache/models
# FAQ 检索阈值（已按语料实测校准）
# 绝对下限：低于该分视为知识库无可靠答案，返回 not_found；
# 中文短文本相似度天然偏高（域外问题可达 ~0.54，域内改写提问 ~0.61 起），故取 0.57。
FAQ_MIN_SCORE=0.57
# 相对比例：只保留与最佳命中足够接近的候选（一问一答场景，弱相关应被排除）。
FAQ_RELATIVE_SCORE_RATIO=0.85
```

说明：

- 匿名模式已关闭，`AUTH_REQUIRED` 不需要配置，也不能通过环境变量重新开启匿名访问。
- PostgreSQL 是唯一的关系型存储；未配置、驱动缺失或无法连接时，服务会显式失败，不会回退到 SQLite。
- 首次连接时程序会懒建表（安全网）。**部署以** `python -m finance_agent.cli.migrate` **为准**：默认应用结构脚本（`migrations/001`–`004`、`006`、`008`、`011`、`013`、`014`），`CREATE EXTENSION IF NOT EXISTS vector` 后应用 FAQ（`migrations/009`、`010`、`012`）；`--seed` 再执行 `migrations/007_product_seed.sql`（`ON CONFLICT` 幂等）。失败显式退出。**pgvector 只在 FAQ 索引/检索时使用**，不属于 API 启动前置条件；缺少 pgvector 只影响 FAQ，不影响登录、对话与管理接口。
- **新增列必须配幂等 ALTER。** `migrations/001_base_schema.sql` 用的是 `CREATE TABLE IF NOT EXISTS`，对已经建好的库**不会补列**。因此给既有表加列时，不能只改 001 的建表语句，必须在编号更大的脚本里同时加一条 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`（参照 `006`/`013`）。漏掉这一步会让旧库缺列——历史上 `products.recommended_holding_period` 就是这样丢的，并连带 `migrations/007_product_seed.sql` 无法应用。可用下面的漂移诊断工具把关：
- 管理员接口（clear-records、商品上下架、用户总览）依赖两条路径，取并集：
  - 库内角色 `finance.users.is_admin`（正式路径，可用 `finance_agent.cli.bootstrap_admin` 授予）；
  - 环境变量 `ADMIN_CUSTOMER_IDS` 白名单（兼容路径，逗号分隔的 customer_id）。

  两条都不满足时所有管理员接口返回 403，前端会隐藏对应面板。角色查询失败时**失败关闭**（按非管理员处理），不会因数据库故障放行。
- 混合编排只有一条执行路径：Supervisor Graph（分类 → 会话/澄清 或 领域任务铺开 + `Send` 并行扇出 → 缺参追问 → 汇合 → 统一合规出口）。单领域与多领域走同一条路径，只差扇出数量；异常显式返回 `run_status="failed"`，不会静默回退到任何旧路径。
- 不要将包含真实密钥的 `.env` 文件提交到版本库。

### 3.1 FAQ 索引、Celery worker 与异步状态

FAQ 索引/检索需要 pgvector 扩展。安装（Debian/Ubuntu 示例）并在业务库启用：

```bash
apt-get install postgresql-15-pgvector   # 版本需与 PostgreSQL 主版本一致
psql -d advisor -c 'CREATE EXTENSION IF NOT EXISTS vector;'
```

FAQ 原文位于 `docs/faq/*.md`，每个问答以 `## FAQ-001 标题` 的二级标题组织（一个问答一个 chunk）。发布索引版本：

```bash
python -m finance_agent.cli.index_faq --root docs/faq --model-cache-dir .cache/models
```

该命令先校验全部文档，再在单事务内写入向量与全文值、切换活跃版本；任一文档校验失败则整批不发布。缺少 pgvector 时命令会给出明确的安装提示，不会影响其它功能。

启动 CPU 密集量化计算的独立 worker（使用 `CELERY_REDIS_DB` 的独立 Redis DB 与 `CELERY_QUANT_QUEUE` 队列）：

```bash
celery -A finance_agent.infrastructure.jobs.celery_app:celery_app worker -Q finance.quant -l info
```

Celery 任务只计算并写结果，不调用 LangGraph；未在同步预算内完成的量化任务会写入 `AsyncJobRef` 并中断图（`awaiting_quant`），可经鉴权的异步状态端点查询并恢复：

```text
GET /api/runs/{task_id}
```

该端点先校验 `(customer_id, conversation_id)` 归属，再读取异步状态或恢复原始 `thread_id` 的图。

checkpoint 的 `thread_id` 为复合键 `v1:{authenticated_user_id}:{conversation_id}`：不同用户的相同 `conversation_id` 不共享状态；旧键仅在确认会话归属后才会被读取并迁移到新键。

### 4. 启动 Redis

确保 Redis 可通过 `REDIS_URL` 连接。例如本地默认地址为：

```text
redis://localhost:6379/0
```

### 5. 启动后端

在项目根目录运行：

```bash
uvicorn finance_agent.main:app --reload --host 127.0.0.1 --port 8000
```

容器内必须监听 `0.0.0.0`（环境变量 `UVICORN_HOST`，本地默认仍为 `127.0.0.1`）。

启动后可访问：

- API：http://127.0.0.1:8000
- Swagger：http://127.0.0.1:8000/docs
- ReDoc：http://127.0.0.1:8000/redoc

### 6. 安装并启动前端

打开另一个终端：

```bash
cd frontend
npm install
npm run dev
```

访问 http://localhost:5173。前端开发服务器会将 `/api` 请求代理到 `http://127.0.0.1:8000`。

### 7. 一键启动（Windows 开发）

上面 4-6 步合计要开三个终端，且顺序不能错：数据库没就绪就起后端会直接 `connection timeout`。
`scripts/start-all.ps1` 把整套**开发**环境按依赖顺序拉起，**每一步都等真正就绪才继续**。
**生产/预发请走下一节 Docker Compose**，不要用本脚本当上线入口。

```powershell
# 显式调用
powershell -ExecutionPolicy Bypass -File scripts\start-all.ps1
```

它按顺序做这些事：

1. 确保 Docker Desktop 已运行，并启动 `postgres-prod` / `redis-prod` 容器；
2. **用应用自身的配置探测**数据库与 Redis 可连接（不是只看端口通不通，因此能同时验证
   库名、密码、目标库是否正确）；
3. 启动后端，并轮询 `/api/health` 直到真正响应；
4. 启动 Celery worker（量化计算队列）；
5. 启动前端，并确认它真的能返回页面。

每一步都在独立窗口运行，日志可随时查看。脚本**幂等**：已在运行的服务会被识别并跳过，
不会重复拉起（Celery 不占固定端口，按进程判重，避免多 worker 争抢同一队列）。
任一步在超时内未就绪就报错退出，不会谎报成功。

常用参数：

```powershell
# 只起数据库 + 后端（不跑前端和量化计算）
.\scripts\start-all.ps1 -SkipCelery -SkipFrontend

# 后端带热重载（改代码即生效）
.\scripts\start-all.ps1 -Reload

# 指定端口
.\scripts\start-all.ps1 -BackendPort 8000 -FrontendPort 5173
```

停止：

```powershell
# 只停应用进程，保留数据库/Redis 容器
powershell -ExecutionPolicy Bypass -File scripts\stop-all.ps1

# 连容器一起停
.\scripts\stop-all.ps1 -IncludeDocker
```

停止脚本按「本项目进程及其后代」精确终止，而不是按端口杀进程，因此不会误伤同机的其他
Python/Node 项目。它会额外处理 `uvicorn --reload` 的派生工作进程——该进程命令行不含项目标识，
且监听 socket 由已被终止的父进程创建（Windows 会把持有者记成那个已死的 PID），是"停了但端口
还占着"的常见根源。结束后会复核端口是否真正释放并如实报告。

### 8. Docker 预发

生产/预发走 Compose：Postgres（pgvector）、Redis、一次性 `migrate`、API、Celery worker、Nginx 前端。
密钥只从环境注入，不打进镜像；FAQ embedding 权重不烤进镜像，挂 `.cache/models`。
Linux 入口：`scripts/start-all.sh`（`docker compose up -d --wait`）。

1. 复制 `.env.example` → `.env`，填 `DEEPSEEK_API_KEY`、`POSTGRES_PASSWORD`、意图模型 key；`APP_ENV=production`。
2. `docker compose up -d --build`
3. `docker compose exec api python -m finance_agent.cli.bootstrap_admin --username admin`（生产拒绝弱口令，已在 bootstrap 里）
4. `docker compose exec api python -m finance_agent.cli.index_faq --root docs/faq`
5. 打开 `http://localhost`（nginx:80），验证登录、对话、商品货架、健康检查 200
6. 确认 Celery 容器在跑，否则股票技术指标会停在 processing

首次 FAQ 索引会从 Hugging Face 拉 `BAAI/bge-small-zh-v1.5` 到挂载的 `.cache/models`，之后重启复用。
同源 Nginx 反代后 `CORS_ALLOW_ORIGINS` 可留空；Compose 已设 `TRUST_PROXY=true`、`UVICORN_HOST=0.0.0.0`。

```bash
cp .env.example .env
# 编辑 .env 后：
./scripts/start-all.sh
# 或：
docker compose up -d --build
```

## 使用流程

1. 打开前端页面并注册账号（**后台管理员**无需注册，本地开发用内置账号
   `admin` / `admin123` 直接登录，详见「管理员账号」一节）。
2. 使用注册的用户名和密码登录。
3. 登录成功后，前端会在 API 请求中自动携带 `Authorization: Bearer <token>`。
4. 登录用户可以创建会话、发送投顾问题、查看画像和历史记录。
5. 注销账户会删除认证记录，以及该用户的会话、画像、模拟交易和其他业务数据。

未登录或令牌无效的业务请求返回 HTTP `401`。访问其他用户的资源返回 HTTP `403`。`customer_id` 仅用于标识当前登录用户，不能通过请求体或 `X-Customer-ID` 请求头伪造身份。

### 模拟交易流程

前端顶部导航分四个页面，登录后即可切换：

| 页面 | 路径 | 用途 |
| --- | --- | --- |
| 投顾对话 | `/chat` | 原有对话、画像与历史记录 |
| 商品 | `/market` | 商品货架，按金额或份额申购 |
| 持仓 | `/positions` | 持仓明细与盈亏，部分/全部卖出，一键清仓 |
| 账户 | `/account` | 账户数据面板、充值、资金流水与成交记录 |

典型路径：先在「账户」充值虚拟资金 → 到「商品」申购 → 在「持仓」查看盈亏并卖出或清仓 →
回到「账户」核对总资产与盈亏。也可以在「投顾对话」里直接问"我的持仓怎么样""账户里还有多少钱"，
由账户领域只读地给出同一份口径的数据。

与真实交易的区别（均为有意设计）：

- **无初始资金**：账户首次访问自动开立但余额为 0，必须先充值；单笔充值有上限。
- **按最新净值即时成交**：没有撮合、没有 T+N 确认，买入与赎回都立即完成。
- **费率未披露时不臆造**：产品费率缺失时照常成交，但订单会带
  `fee_unavailable:*` 限制项并在界面提示，不会静默按某个猜测值计算。
- **无净值不可交易**：取不到最新净值的商品仍会展示，但标记为不可申购/不可赎回。
- **仓容口径不隐藏缺口**：任一持仓缺少净值时，`market_value_complete=false` 且列出
  `pricing_issues`，界面显式提示市值口径不完整，而不是把市值悄悄算小。
- **对话不代客操作**：账户领域是只读的，命中"买入/卖出/清仓/充值"只返回引导文案。
  下单与充值必须由用户在页面显式完成。

### 管理员账号

本地开发环境预置一个管理员账号，用于登录后台（`/admin`）：

| 用户名 | 密码 | customer_id |
| --- | --- | --- |
| `admin` | `admin123` | `CUST000088` |

> ⚠️ **仅限本地开发。** 这是开发固定口令，明文落在版本库里，**上线前必须改掉**：
> 用下面的脚本重置，或改由 `.env` / 部署密钥注入 `FINANCE_ADMIN_PASSWORD`。
> 生产环境沿用该口令等于把后台开放给任何人。

管理员不是固定账号，而是**角色**：由 `finance.users.is_admin` 决定，
并与 `ADMIN_CUSTOMER_IDS` 白名单取并集。授予/回收角色用引导脚本（幂等）：

```bash
# 创建（或提升）admin 并重置其密码；默认把其他用户全部降为普通用户
python -m finance_agent.cli.bootstrap_admin --username admin --password '你的密码'
# 也可用环境变量传密码，避免出现在 shell 历史里
FINANCE_ADMIN_PASSWORD='你的密码' python -m finance_agent.cli.bootstrap_admin --username admin
# 只查看当前角色分布，不写入
python -m finance_agent.cli.bootstrap_admin --dry-run
```

密码不回显、明文不落库（PBKDF2-SHA256 + 随机盐），因此**无法从库或仓库反查**——
忘记口令时只能按上面的命令重置。

脚本会提示检查 `.env`：白名单与库内角色是并集，把已降级的用户留在
`ADMIN_CUSTOMER_IDS` 里会让他继续拥有管理员权限，因此日常授权请只用脚本、白名单留空。

管理员与普通用户看到的是**两套互不重叠的界面**：管理员登录后直接进入独立的后台页面
（`/admin`），不会渲染投顾对话、商品、持仓、账户等用户侧入口；普通用户也进不去 `/admin`
（前端跳回 `/chat`，后端接口另返回 403 兜底）。角色在本地登录态与服务端不一致时（如刚被
授予或撤销），前端会在身份刷新后重新校正路由，不会渲染出对方的界面。

未登录访问后台地址时**守卫不做重定向**：登录页由 `App.vue` 依据登录态渲染，此时后台
`router-view` 根本不挂载，因此不会泄漏任何受保护内容；登录后会被直接送回后台页面。
改为重定向到 `/chat` 反而会触发 Vue Router 的"重定向到自身"判定并中止整次导航，
把地址栏留在 `/admin/*`。

后台按功能分区成独立页面，通过顶部「后台导航」切换，每页只展示一个功能模块：

| 页面 | 路径 | 用途 |
| --- | --- | --- |
| 用户与持仓 | `/admin/users` | 全部用户的资金、持仓数量与盈亏；点开可看某人的持仓明细 |
| 商品管理 | `/admin/products` | 发行/编辑商品；下架或重新上架 |

`/admin` 重定向到 `/admin/users`。每个子路由都独立标注管理员守卫，不依赖父记录
`meta` 的隐式合并 —— 守卫漏判会让普通用户直接看到后台，代价太高，不值得省这几行。

用户总览里的账户数字与用户自己在「账户」页看到的同源（都由模拟交易服务计算），
管理端不另立口径。

下架是**软下架**（`products.is_active=false`），不是删除：

- 商品与历史成交记录都保留。`finance.orders.product_code` 有外键指向
  `finance.products(code)`，删除有成交记录的商品会直接外键失败；即便删得掉，
  历史成交与持仓也会失去可解释的标的。
- 下架后该商品从用户货架消失、不再出现在名称候选里，申购被拒（`product_offline`）。
- **既有持仓仍然可以赎回** —— 只挡买入，否则用户会被困在无法退出的持仓里。

## API 概览

| 方法 | 路径 | 说明 | 是否需要登录 |
| --- | --- | --- | --- |
| `POST` | `/api/register` | 注册用户 | 否 |
| `POST` | `/api/login` | 登录并获取令牌 | 否 |
| `POST` | `/api/logout` | 注销当前令牌 | 是 |
| `GET` | `/api/me` | 获取当前用户信息 | 是 |
| `POST` | `/api/chat` | 同步投顾对话 | 是 |
| `POST` | `/api/chat/stream` | SSE 流式投顾对话 | 是 |
| `POST` | `/api/chat/stop` | 停止指定运行 | 是 |
| `GET` | `/api/profile/{customer_id}` | 获取用户投资画像 | 是，仅限本人 |
| `GET` | `/api/history/{customer_id}` | 获取对话历史 | 是，仅限本人 |
| `POST` | `/api/conversations/{customer_id}` | 创建新会话 | 是，仅限本人 |
| `GET` | `/api/conversations/{customer_id}` | 获取会话列表 | 是，仅限本人 |
| `GET` | `/api/conversations/{customer_id}/{conversation_id}/messages` | 获取会话消息 | 是，仅限本人 |
| `DELETE` | `/api/conversations/{customer_id}/{conversation_id}` | 删除会话 | 是，仅限本人 |
| `POST` | `/api/reset/{customer_id}` | 重置用户会话 | 是，仅限本人 |
| `POST` | `/api/admin/clear-records` | 清除记录 | 是，全部清除仅管理员 |
| `GET` | `/api/admin/users` | 全部用户及账户概览（资金、持仓、盈亏） | 是，仅管理员 |
| `GET` | `/api/admin/users/{customer_id}/portfolio` | 指定用户的账户与持仓明细 | 是，仅管理员 |
| `GET` | `/api/admin/products` | 完整商品列表（含已下架） | 是，仅管理员 |
| `POST` | `/api/admin/products` | 发行/编辑商品 | 是，仅管理员 |
| `POST` | `/api/admin/products/{code}/offline` | 下架商品（软下架，不可申购） | 是，仅管理员 |
| `POST` | `/api/admin/products/{code}/publish` | 重新上架商品 | 是，仅管理员 |
| `DELETE` | `/api/account` | 删除当前账户 | 是 |
| `GET` | `/api/portfolio/products` | 商品货架（净值、风险等级、费率） | 是 |
| `GET` | `/api/portfolio/products/{code}` | 单个商品详情 | 是 |
| `GET` | `/api/portfolio/account` | 账户数据面板 | 是 |
| `GET` | `/api/portfolio/positions` | 持仓明细（含浮动盈亏） | 是 |
| `POST` | `/api/portfolio/deposit` | 充值虚拟资金 | 是 |
| `POST` | `/api/portfolio/orders` | 申购 / 赎回 | 是 |
| `POST` | `/api/portfolio/liquidate` | 一键清仓 | 是 |
| `GET` | `/api/portfolio/orders` | 成交记录 | 是 |
| `GET` | `/api/portfolio/transactions` | 资金流水 | 是 |
| `GET` | `/api/health` | 服务健康检查 | 否 |

完整请求和响应结构请以 Swagger 文档为准。

模拟交易接口的身份**只从 Bearer Token 解析**，路径与请求体都不带 `customer_id`，
因此不存在通过参数读取他人账户的可能。所有写接口（充值、下单、清仓）都接受可选的
`idempotency_key`：同一键重复提交只入账一次，用于抵御网络重试造成的重复扣款。
资金操作在单个数据库事务内完成并对账户行加锁，避免并发下单超支。

### 注册和登录示例

```bash
# 注册
curl -X POST "http://127.0.0.1:8000/api/register" \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"password123","display_name":"Alice"}'

# 登录，保存返回的 token 和 customer_id
curl -X POST "http://127.0.0.1:8000/api/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"password123"}'
```

### 登录后发起对话

将登录接口返回的令牌替换为 `<token>`。请求身份只从 Bearer Token 解析，不要传 `X-Customer-ID`：

```bash
curl -X POST "http://127.0.0.1:8000/api/chat" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "message":"我有10万元，风险偏好稳健，想分析贵州茅台并给出配置建议",
    "conversation_id":""
  }'
```

查询当前用户：

```bash
curl "http://127.0.0.1:8000/api/me" \
  -H "Authorization: Bearer <token>"
```

## 常用开发命令

后端编译检查：

```bash
python -m compileall -q finance_agent
```

运行测试：

```bash
pytest -q
```

产品数据灌库（产品解读专家的唯一事实来源；数据由运维准备，本仓库不接入外部产品数据源）：

```bash
# 由结构化数据生成幂等 SQL；校验失败时不产出任何文件
python -m finance_agent.cli.generate_product_seed \
  --input finance_agent/cli/data/products.sample.json \
  --output migrations/007_product_seed.sql
# 再按既有方式应用到数据库（例如 psql -f migrations/007_product_seed.sql）
```

生成器只接受 `products` / `holdings` / `performance` 三类记录，按外键顺序输出
`INSERT ... ON CONFLICT`（明细表先按产品清空再写入，因此可重复执行）；所有值经类型
白名单与单引号加倍转义。`finance_agent/cli/data/products.sample.json` 是可直接使用的样例。

模拟交易的端到端自检（需要可用的 PostgreSQL；用一次性用户与商品跑完
充值 → 申购 → 持仓 → 部分赎回 → 清仓 → 注销级联，结束后自动清理）：

```bash
python -m finance_agent.cli.verify_portfolio_live
```

该命令走**真实** `PostgresPortfolioStore`，是模拟交易持久化层的实机闸门：改动
`finance_agent/infrastructure/persistence/postgres/` 下任何 store 之后都必须跑一遍。
**不变式**：`_PostgresBaseStore` 的子类可以覆写 `transaction()`（在其中调用
`_ensure_schema()`，`PostgresPortfolioStore` 就是如此），但 `_apply_schema()` 必须用原始
`TransactionRunner` 跑迁移——`_schema_lock` 是不可重入的 `threading.Lock`，迁移若再经过
`self.transaction()` 就会与 `_ensure_schema()` 形成同线程自死锁。这类死锁一旦发生在
事件循环上，整个 API（含 `/api/health`）都会失去响应。

管理员账号的创建与角色授予（幂等；详见「管理员账号」一节）。
本地开发内置 `admin` / `admin123`，如需更换口令：

```bash
python -m finance_agent.cli.bootstrap_admin --dry-run                 # 查看当前角色分布
python -m finance_agent.cli.bootstrap_admin --username admin --password '你的密码'
```

模拟交易的建表脚本为 `migrations/011_portfolio.sql`（账户、资金流水、委托与持仓）。
部署时由 `python -m finance_agent.cli.migrate` 统一应用；进程内 `_ensure_schema` / `setup_schema`
仍作为懒建表安全网，首次访问业务存储时会走同一份 `SCHEMA_APPLY_ORDER`。

管理后台的角色与上下架列为 `migrations/013_admin_console.sql`（`users.is_admin`、
`products.is_active`）。同样纳入统一 migrate 与懒建表。

库表漂移诊断（对比 `migrations/` 声明的期望结构与线上实际结构，可用于 CI 把关）：

```bash
python -m finance_agent.cli.diagnose_schema_drift
```

它会把建表脚本应用到一个一次性探针库作为权威期望结构，再与线上库逐表逐列比对，
结束后自动删除探针库；线上库只执行只读查询。发现缺失表/列或类型不一致时退出码为 1，
`--keep-probe` 可保留探针库以便人工检查。

构建前端：

```bash
cd frontend
npm run build
```

## 数据与缓存

- `POSTGRES_DSN`：PostgreSQL 完整连接串；未设置时使用 `POSTGRES_HOST`、`POSTGRES_PORT`、`POSTGRES_USER`、`POSTGRES_PASSWORD` 和 `POSTGRES_DB` 组成连接串。
- `REDIS_URL`：Redis 地址；保存用户画像、滑动对话窗口和摘要等运行时记忆。
- 对话记忆（窗口/摘要）的 Redis 键按客户隔离：`finance_cs:conv:{customer_id}:{conversation_id}:window` 与 `:summary`。因此仅凭 `conversation_id` 无法读写他人记忆。升级到本版本后，旧键格式（`finance_cs:conv:{conversation_id}:*`）不会再被读取，会在 TTL 到期后自然淘汰（记忆本身为 best-effort，不影响对话正确性）；`POST /api/admin/clear-records` 的 `finance_cs:*` 扫描仍会清理这些残留键。
- PostgreSQL 模式下，`users` 是唯一用户主体表，`conversations`、`user_profiles`、`sessions` 和运行审计记录均通过 `customer_id` 关联到已注册用户，不再保留独立的 `customers` 主体表。
- Tushare MCP 返回的是最近交易日数据，并非交易所盘中实时行情。

### 股票数据源

- 默认顺序为 `DATA_PROVIDER_ORDER=akshare,tushare_mcp,baostock`，并**按方法**降级：某个源未声明该能力（例如 AKShare 的交易日历）不会标记为“降级”，只有真实取数失败才会。`last_metadata` 里 `unsupported` 与 `failures` 是分开的两项。
- AKShare 日线走新浪源 `stock_zh_a_daily`；东财的 `stock_zh_a_hist` 在部分网络环境下会被按 URL 过滤（TCP 与 TLS 正常但请求被直接关闭），同包内无法修复，因此只作回退。**腾讯源不参与前复权**：它的复权口径与新浪/BaoStock 不同（同一交易日收盘价 1444.42 vs 1435.70），混用会让回测不可复现。
- 前复权基准口径为**新浪 / BaoStock**（两者逐字节一致）。跨源比对请比**区间收益率**，不要比绝对价格——复权锚点不同是合法差异。
- 日估值来源：AKShare `stock_value_em`（东财；起点为 `max(2018-01-02, 上市日)`；**不含股息率**）、BaoStock `peTTM/pbMRQ`（免 token，仅沪深）、Tushare `daily_basic`（需 ≥2000 积分；是唯一提供股息率 `dv_ratio`/`dv_ttm` 的来源）。
- BaoStock **不支持北交所**（`bj.` 报错、`sh.`/`sz.` 会静默返回 0 行），本仓库对北交所代码显式报错。已废止的 `43`/`83`/`87` 开头代码同样显式报错而**不做猜测映射**：末三位规则会把 `830799`（诺思兰德，现行为 `920047`）错指到另一家公司。
- 行情与估值按 `(provider, code, 复权口径, 日期窗口)` 落盘缓存，默认 TTL 3600 秒，位于仓库根目录 `.cache/quotes`（`QUOTE_CACHE_TTL_SECONDS=0` 可关闭）。缓存写入失败只记告警，不影响取数。
- 行业与披露日来自东财业绩报表 `stock_yjbb_em`（按报告期，自动回退到最近已披露期）：行业为**申万二级**（如"白酒Ⅱ"）并与 A 股清单合并，供候选搜索的行业关键词匹配；披露日按报告期回填到财务指标。二者均为**补全信息**——取数失败时对应字段缺失、限制项如实呈现，不阻断分析。财务指标接口必须显式传 `start_year`，否则默认 `1900` 会返回 0 行并使基本面评分退化为中性分。
- 规则版本当前为 `research_rules/v1.2`：**v1.2** 起适配度（suitability）在缺值时不再默认 50.0，改为排除该项按实际可算项加权（此前画像完整的请求会被静默注入中性适配度、可能改变结论）；**v1.1** 补上 PE/PB 后基本面评分由 5 项而不是 3 项平均而成。口径变化必须换版本号，审计记录按其版本号精确重放。旧版本 `v1`/`v1.1` 仍然保留。
- **使用限制：** 这些第三方行情数据仅供个人研究使用，不得再分发；本地缓存亦仅供本机使用。

## 安全注意事项

- 必须使用 HTTPS 或受信任的内网传输真实登录令牌。
- 不要将 `DEEPSEEK_API_KEY`、数据库密码或登录令牌写入代码、日志或版本库。
- 生产环境应限制 PostgreSQL、Redis 和 FastAPI 管理端口的网络访问。
- 删除账户和 PostgreSQL 身份迁移会清理关联业务数据，执行前请确认数据库备份策略。
- **上线前必做：**
  - 设置 `APP_ENV=production`（关闭 `/docs`、`/redoc`、`/openapi.json`，根路径不再枚举接口）。
  - 设置 `CORS_ALLOW_ORIGINS` 为实际上线的前端源，不要沿用 localhost。
  - 用 `FINANCE_ADMIN_PASSWORD` + `finance_agent.cli.bootstrap_admin` 创建管理员，**禁止**使用文档中的 `admin` / `admin123`。
  - 登录/注册有进程内频率限制；多副本部署时请在网关再加一层。
  - `/api/health` 在 PostgreSQL 不可用或编排无法初始化时返回 HTTP 503；`/api/health/degradation` 仅管理员可访问。

## 常见问题

### 启动时报 DEEPSEEK_API_KEY 错误

请先在当前操作系统会话中设置真实的 `DEEPSEEK_API_KEY`，再启动 Uvicorn。程序不会用 `.env` 文件覆盖该密钥，也不会接受示例占位值。

### Redis 无法连接

确认 Redis 服务已启动，并检查 `REDIS_URL` 的主机、端口和数据库编号。Redis 用于运行时记忆；认证和持久化业务数据始终存储在 PostgreSQL。

### PostgreSQL 模式启动失败

确认已按项目依赖安装 PostgreSQL 驱动与 checkpoint 包，并检查 `POSTGRES_DSN` 或 PostgreSQL 组件配置。缺少依赖、未配置或连接失败时，服务会明确报错，不会回退到 SQLite。

### Tushare MCP 或行情数据不可用

确认 `TUSHARE_MCP_URL` 包含有效端点和 token，并检查 `TUSHARE_MCP_TIMEOUT`。数据源返回的是最近交易日数据，不保证是交易所盘中实时行情。

若 **K 线为空**：先确认 AKShare 的新浪源接口可达（`ak.stock_zh_a_daily`）。东财的 K 线接口在部分网络环境下会被按 URL 过滤，属于环境问题，换 header、换镜像域名都无效。

若 **估值缺失**：确认 `ak.stock_value_em` 或 BaoStock 是否可达，并查看快照的限制项——缺少 PE/PB 现在会以 `fundamental_missing:pe_ttm` 这样的**逐字段**原因码记录，而不是静默降级。注意北交所与已废止代码会被显式拒绝，那属于预期行为。

若 **本地缓存干扰排查**：把 `QUOTE_CACHE_TTL_SECONDS` 设为 `0` 关闭缓存，或删除仓库根目录下的 `.cache/quotes`。

### 商品 / 持仓 / 账户页面没有数据

先分辨是「数据缺失」还是「后端被卡住」：请求 `http://127.0.0.1:8000/api/health`。
若连一个不存在的路径（例如 `/api/nope`）都超时、而 TCP 仍能连上，说明**事件循环被阻塞**，
而不是库里没数据。此时停止后端进程并重新启动即可恢复（启动前必须按上文设置
`DEEPSEEK_API_KEY`，缺失时应用导入即失败，端口被 `--reload` 父进程占着却无人响应，症状与此完全一致）。

根因类别与防线：

- 持仓/账户接口背后是同步 psycopg 调用。模拟交易、管理后台与健康检查的路由因此一律是同步
  `def`，由 Starlette 放进线程池执行——慢查询只会占住一个 worker，不会冻住 `/api/health`。
  `tests/architecture/test_api_structure.py::test_blocking_route_handlers_stay_synchronous`
  会挡住把它改回 `async def` 的改动。
- 存储层懒建表的自死锁（见「常用开发命令」中 `verify_portfolio_live` 的不变式）曾造成同样的
  整站无响应；`tests/integration/test_postgres_stores.py` 的看门狗测试守着它。
- 前端无需改动：接口恢复后刷新浏览器即可看到商品货架、持仓明细与账户面板。
