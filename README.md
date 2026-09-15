# Finance Agent

基于 LangGraph 多 Agent 协作的 A 股智能投顾系统。系统通过自然语言收集用户投资需求，完成用户画像提取、股票识别、行情与财务数据获取、基本面分析、技术分析、市场洞察和合规审查，并提供 Vue 3 Web 界面及 FastAPI 接口。

## 功能特性

- 多 Agent 工作流：由 Supervisor 规划并协调各专业 Agent。
- A 股数据：默认按 `DATA_PROVIDER_ORDER` 在 AKShare / Tushare MCP / BaoStock 之间按方法降级，获取股票信息、最近交易日行情、历史 K 线和财务指标。
- 可选数据源：配置 `TUSHARE_MCP_URL` 后启用 Tushare MCP 作为其中一路（需 ≥2000 积分才能提供股息率）。
- 智能选股：可选接入联网搜索，辅助识别行业、主题和股票名称。
- 基本面与技术面分析：支持财务指标及 MACD、KDJ、RSI、BOLL、MA、WR 等指标。
- 市场洞察：大盘概览、市场情绪、资金面与政策事件影响，只回答市场整体问题，不输出个股结论。
- 合规审查：对最终回答执行敏感内容和投资风险检查。
- 流式对话：支持基于 SSE 的实时响应。
- 用户系统：支持注册、登录、Bearer Token 认证、会话管理和账户注销。
- 多层记忆：Redis 保存运行时记忆，PostgreSQL 保存认证、业务数据和 LangGraph checkpoint。
- 强制登录：匿名访问已关闭。聊天、画像、历史记录、会话管理和账户操作都必须使用有效登录令牌。

## 工作流程

```text
用户请求
   |
   v
用户认证
   |
   v
Supervisor（任务规划）
   |
   +--> Profile Extraction（投资画像提取）
   +--> 股票识别与校验
   +--> Data Fetch（按 Provider 顺序降级取数）
   +--> Stock Analysis（基本面 + 技术面分析）
   +--> Market Insight（市场洞察：大盘/情绪/资金面/政策事件）
   +--> Compliance（合规审查）
   |
   v
最终回答
```

Supervisor 会根据用户意图选择所需节点，并非每次请求都会执行完整流程。多标的请求（选股推荐、
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
- Element Plus
- ECharts
- Axios

## 项目结构

```text
FinanceAgent/
├── finance_agent/
│   ├── agents/              # Supervisor 和各专业 Agent
│   ├── api/                 # FastAPI 路由、请求模型和 SSE
│   ├── contracts/           # 请求、响应和运行审计契约
│   ├── data/                # 认证、业务存储、PostgreSQL 和数据源
│   ├── middleware/          # 内容过滤和模型重试
│   ├── orchestrator/        # 工作流编排、记忆、状态和业务工具
│   ├── config.py            # 模型及运行环境配置
│   └── main.py              # FastAPI 应用入口
├── frontend/                # Vue 3 前端
├── tests/                   # pytest 测试
├── pyproject.toml
├── requirements.txt
└── README.md
```

## 环境要求

- Python 3.10 或更高版本
- Node.js 18 或更高版本
- Redis 服务
- 有效的 DeepSeek API Key
- PostgreSQL 仅在需要使用 PostgreSQL 存储时安装并配置

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

安装开发和测试依赖：

```bash
pip install -e ".[dev]"
```

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

# 管理员 customer_id，多个值用逗号分隔
# ADMIN_CUSTOMER_IDS=CUST000001,CUST000002

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

# 混合 LangGraph 编排预算（单一执行路径：Root Graph）
ORCHESTRATION_REACT_STEPS=4
ORCHESTRATION_PLAN_TASKS=8
ORCHESTRATION_REPLANS=2
ORCHESTRATION_COMPLIANCE_REWRITES=1
ORCHESTRATION_GRAPH_STEPS=32

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
# 归一化 RRF 融合分阈值；低于该值的 FAQ 命中判为 not_found
FAQ_MIN_SCORE=0.3
```

说明：

- 匿名模式已关闭，`AUTH_REQUIRED` 不需要配置，也不能通过环境变量重新开启匿名访问。
- PostgreSQL 是唯一的关系型存储；未配置、驱动缺失或无法连接时，服务会显式失败，不会回退到 SQLite。
- 首次连接时程序会自动创建认证、业务、审计、主题注册表与异步任务表。**pgvector 只在 FAQ 索引/检索时使用**（`sql/009_faq_vector.sql`），不属于启动前置条件；缺少 pgvector 只影响 FAQ，不影响登录、对话与管理接口。
- 管理员接口（主题注册表、待审核线索、clear-records）依赖 `ADMIN_CUSTOMER_IDS` 白名单；未配置时所有管理员接口返回 403，前端会隐藏对应面板。
- 混合编排只有一条执行路径：Root Graph（分类 → 单领域 Domain ReAct / 复合 Plan-and-Execute → 统一合规出口）。异常显式返回 `run_status="failed"`，不会静默回退到任何旧路径。
- 不要将包含真实密钥的 `.env` 文件提交到版本库。

### 3.1 FAQ 索引、Celery worker 与异步状态

FAQ 索引/检索需要 pgvector 扩展。安装（Debian/Ubuntu 示例）并在业务库启用：

```bash
apt-get install postgresql-15-pgvector   # 版本需与 PostgreSQL 主版本一致
psql -d advisor -c 'CREATE EXTENSION IF NOT EXISTS vector;'
```

FAQ 原文位于 `docs/faq/*.md`，每个问答以 `## FAQ-001 标题` 的二级标题组织（一个问答一个 chunk）。发布索引版本：

```bash
python -m finance_agent.faq index --root docs/faq --model-cache-dir .cache/models
```

该命令先校验全部文档，再在单事务内写入向量与全文值、切换活跃版本；任一文档校验失败则整批不发布。缺少 pgvector 时命令会给出明确的安装提示，不会影响其它功能。

启动 CPU 密集量化计算的独立 worker（使用 `CELERY_REDIS_DB` 的独立 Redis DB 与 `CELERY_QUANT_QUEUE` 队列）：

```bash
celery -A finance_agent.celery_app:celery_app worker -Q finance.quant -l info
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

## 使用流程

1. 打开前端页面并注册账号。
2. 使用注册的用户名和密码登录。
3. 登录成功后，前端会在 API 请求中自动携带 `Authorization: Bearer <token>`。
4. 登录用户可以创建会话、发送投顾问题、查看画像和历史记录。
5. 注销账户会删除认证记录，以及该用户的会话、画像和相关业务数据。

未登录或令牌无效的业务请求返回 HTTP `401`。访问其他用户的资源返回 HTTP `403`。`customer_id` 仅用于标识当前登录用户，不能通过请求体或 `X-Customer-ID` 请求头伪造身份。

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
| `GET` | `/api/admin/themes/{theme_id}/leads` | 查看主题待核验线索 | 是，仅管理员 |
| `POST` | `/api/admin/theme-leads/{lead_id}/review` | 审核主题线索 | 是，仅管理员 |
| `GET` | `/api/admin/themes` | 查看主题注册表 | 是，仅管理员 |
| `POST` | `/api/admin/themes` | 新增/更新主题（名称、别名、代表股） | 是，仅管理员 |
| `DELETE` | `/api/admin/themes/{theme_id}` | 停用主题（软删） | 是，仅管理员 |
| `DELETE` | `/api/account` | 删除当前账户 | 是 |
| `GET` | `/api/health` | 服务健康检查 | 否 |

完整请求和响应结构请以 Swagger 文档为准。

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

主题候选池的日终刷新（仅处理审核有效且证据未过期的成员）：

```bash
python -m finance_agent.research.refresh --theme-id ai_compute
```

生产调度可在收盘后每日执行一次。也可通过 `THEME_REFRESH_IDS=ai_compute,robotics`
配置多个主题；刷新失败会在 JSON 汇总中记录原因，且不会写入占位评分。

产品数据灌库（产品解读专家的唯一事实来源；数据由运维准备，本仓库不接入外部产品数据源）：

```bash
# 由结构化数据生成幂等 SQL；校验失败时不产出任何文件
python tools/generate_product_seed.py \
  --input tools/data/products.sample.json \
  --output sql/007_product_seed.sql
# 再按既有方式应用到数据库（例如 psql -f sql/007_product_seed.sql）
```

生成器只接受 `products` / `holdings` / `performance` 三类记录，按外键顺序输出
`INSERT ... ON CONFLICT`（明细表先按产品清空再写入，因此可重复执行）；所有值经类型
白名单与单引号加倍转义。`tools/data/products.sample.json` 是可直接使用的样例。

首次建立或补充主题候选池时，配置 `THEME_DISCOVERY_ENDPOINT`、
`THEME_DISCOVERY_SOURCE_NAME`、`THEME_DISCOVERY_SOURCE_CLASS` 和可选的
`THEME_DISCOVERY_API_TOKEN`，再运行：

```bash
python -m finance_agent.research.theme_discovery --theme-id ai_compute
```

外部数据只会作为待核验研究线索写入 PostgreSQL；必须在管理员审核通过后才能参与主题筛选。

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
- 规则版本当前为 `research_rules/v1.2`：**v1.2** 起适配度（suitability）在缺值时不再默认 50.0，改为排除该项按实际可算项加权（此前画像完整的请求会被静默注入中性适配度、可能改变结论）；**v1.1** 补上 PE/PB 后基本面评分由 5 项而非 3 项平均而成。口径变化必须换版本号，否则同一 `(theme, stock, rule_version, as_of)` 键上的 upsert 会覆盖旧口径的历史快照。旧版本 `v1`/`v1.1` 仍然保留，审计记录按其中记录的版本号精确重放。
- **使用限制：** 这些第三方行情数据仅供个人研究使用，不得再分发；本地缓存亦仅供本机使用。

## 安全注意事项

- 必须使用 HTTPS 或受信任的内网传输真实登录令牌。
- 不要将 `DEEPSEEK_API_KEY`、数据库密码或登录令牌写入代码、日志或版本库。
- 生产环境应限制 PostgreSQL、Redis 和 FastAPI 管理端口的网络访问。
- 删除账户和 PostgreSQL 身份迁移会清理关联业务数据，执行前请确认数据库备份策略。

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
