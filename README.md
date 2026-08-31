# Finance Agent

基于 LangGraph 多 Agent 协作的 A 股智能投顾系统。系统通过自然语言收集用户投资需求，完成用户画像提取、股票识别、行情与财务数据获取、基本面分析、技术分析、资产配置和合规审查，并提供 Vue 3 Web 界面及 FastAPI 接口。

## 功能特性

- 多 Agent 工作流：由 Supervisor 规划并协调各专业 Agent。
- A 股数据：通过 Tushare MCP 获取股票信息、最近交易日行情、历史 K 线和财务指标。
- 可选数据源：配置 Tushare MCP URL 后，通过 Streamable HTTP 接入远程数据服务。
- 智能选股：可选接入联网搜索，辅助识别行业、主题和股票名称。
- 基本面与技术面分析：支持财务指标及 MACD、KDJ、RSI、BOLL、MA、WR 等指标。
- 资产配置：计算收益率、波动率等指标并生成组合配置建议。
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
   +--> Data Fetch（Tushare MCP 数据获取）
   +--> Stock Analysis（基本面 + 技术面分析）
   +--> Asset Allocation（资产配置）
   +--> Compliance（合规审查）
   |
   v
最终回答
```

Supervisor 会根据用户意图选择所需节点，并非每次请求都会执行完整流程。

## 技术栈

### 后端

- Python 3.10+
- FastAPI / Uvicorn
- LangChain / LangGraph
- DeepSeek
- Tushare MCP
- Redis
- PostgreSQL
- pandas / NumPy / SciPy

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

# 管理员 customer_id，多个值用逗号分隔
# ADMIN_CUSTOMER_IDS=CUST000001,CUST000002

# Tushare MCP 数据源
# TUSHARE_MCP_URL=https://your-tushare-mcp-endpoint?token=your-token
TUSHARE_MCP_TIMEOUT=30

# 模型和工作流参数
DEEPSEEK_INTENT_MODEL=deepseek-chat
DEEPSEEK_INTENT_TIMEOUT=30
DEEPSEEK_INTENT_MAX_RETRIES=1
LLM_REQUEST_TIMEOUT=45
LLM_MAX_RETRIES=1
FINAL_SYNTHESIS_TIMEOUT=20
DEBATE_ENABLED=true
DEBATE_MAX_ROUNDS=2
DEBATE_TIMEOUT=60
DEBATE_BULL_TEMPERATURE=0.4
DEBATE_BEAR_TEMPERATURE=0.4
DEBATE_SYNTHESIS_TEMPERATURE=0.1
PRODUCT_ANALYSIS_TEMPERATURE=0.2
```

说明：

- 匿名模式已关闭，`AUTH_REQUIRED` 不需要配置，也不能通过环境变量重新开启匿名访问。
- PostgreSQL 是唯一的关系型存储；未配置、驱动缺失或无法连接时，服务会显式失败，不会回退到 SQLite。
- 首次连接时程序会自动创建所需 schema。
- 不要将包含真实密钥的 `.env` 文件提交到版本库。

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

构建前端：

```bash
cd frontend
npm run build
```

## 数据与缓存

- `POSTGRES_DSN`：PostgreSQL 完整连接串；未设置时使用 `POSTGRES_HOST`、`POSTGRES_PORT`、`POSTGRES_USER`、`POSTGRES_PASSWORD` 和 `POSTGRES_DB` 组成连接串。
- `REDIS_URL`：Redis 地址；保存用户画像、滑动对话窗口和摘要等运行时记忆。
- PostgreSQL 模式下，`users` 是唯一用户主体表，`conversations`、`user_profiles`、`sessions` 和运行审计记录均通过 `customer_id` 关联到已注册用户，不再保留独立的 `customers` 主体表。
- Tushare MCP 返回的是最近交易日数据，并非交易所盘中实时行情。

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
