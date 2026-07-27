# Finance Agent

基于 LangGraph 多 Agent 协作的 A 股智能投顾系统。项目通过自然语言收集用户投资需求，自动完成用户画像提取、股票识别、行情与财务数据获取、基本面分析、资产配置和合规审查，并提供 Vue 3 Web 界面及 FastAPI 接口。


## 功能特性

- 多 Agent 工作流：由监督 Agent 规划并协调各专业 Agent。
- A 股数据：通过 BaoStock 获取股票信息、最近交易日行情、历史 K 线和财务指标。
- 智能选股：可选接入百度千帆搜索，辅助识别行业、主题和股票名称。
- 基本面分析：结合财务指标生成结构化分析结果。
- 资产配置：计算收益率、波动率等指标，并进行投资组合优化。
- 合规审查：对最终回答进行敏感内容和投资风险检查。
- 流式对话：支持基于 SSE 的实时响应。
- 用户系统：支持注册、登录、令牌认证和账户管理。
- 多层记忆：使用 Redis 保存对话窗口与用户画像，使用 SQLite 持久化账户及会话。
- 前后端分离：FastAPI 后端配合 Vue 3、Element Plus 和 ECharts 前端。

## 工作流程

```text
用户请求
   ↓
Supervisor（任务规划）
   ↓
Profile Extraction（投资画像提取）
   ↓
股票识别与校验
   ↓
Data Fetch（BaoStock 数据获取，可按股票并行）
   ↓
Fundamental Analysis（基本面分析，可按股票并行）
   ↓
Asset Allocation（资产配置）
   ↓
Compliance（合规审查）
   ↓
最终回答
```

监督 Agent 会根据用户意图选择所需节点，并非每次请求都会执行完整流程。

## 技术栈

### 后端

- Python 3.10+
- FastAPI / Uvicorn
- LangChain / LangGraph
- DeepSeek
- BaoStock
- Redis
- SQLite
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
│   ├── agents/              # 各专业 Agent
│   ├── api/                 # FastAPI 路由、模型与 SSE
│   ├── core/                # 工作流编排、记忆、数据库与共享状态
│   ├── tools/               # BaoStock、搜索、配置、认证和合规工具
│   ├── config.py            # 模型及环境配置
│   ├── finance_agent.db     # 默认 SQLite 数据库
│   └── main.py              # FastAPI 应用入口
├── frontend/                # Vue 3 前端
├── pyproject.toml
├── requirements.txt
└── README.md
```

## 环境要求

- Python 3.10 或更高版本
- Node.js 18 或更高版本
- Redis（推荐；Redis 不可用时部分长期记忆和历史功能会受限）
- 有效的 DeepSeek API Key
- 百度千帆 API Key（可选，仅智能搜索功能需要）

## 快速开始

### 1. 获取项目并创建虚拟环境

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

也可以使用：

```bash
pip install -r requirements.txt
```

如需开发和测试依赖：

```bash
pip install -e ".[dev]"
```

### 3. 配置环境变量

`DEEPSEEK_API_KEY` 必须设置在操作系统环境变量中。当前实现不会从 `.env` 读取该密钥。

Windows PowerShell（当前终端会话）：

```powershell
$env:DEEPSEEK_API_KEY="your-deepseek-api-key"
```

Linux / macOS：

```bash
export DEEPSEEK_API_KEY="your-deepseek-api-key"
```

在项目根目录创建 `.env`，配置其他服务：

```dotenv
REDIS_URL=redis://localhost:6379/0
SQLITE_PATH=finance_agent/finance_agent.db

# 可选：百度千帆智能搜索
QIANFAN_API_KEY=
QIANFAN_SEARCH_MODEL=deepseek-v4-flash
QIANFAN_SEARCH_TIMEOUT=60

# 多意图识别与理财闲聊使用的模型
INTENT_MODEL=deepseek:deepseek-v4-flash
INTENT_CLASSIFIER_MODE=shadow
INTENT_ZERO_SHOT_MODEL=MoritzLaurer/mDeBERTa-v3-base-mnli-xnli
INTENT_MODEL_CACHE_DIR=.cache/huggingface
INTENT_MAX_LENGTH=256
INTENT_SCORE_THRESHOLD=0.5
INTENT_DEVICE=-1
INTENT_MODEL_TIMEOUT=10
INTENT_MODEL_MAX_RETRIES=1

# BaoStock 本地缓存
STOCK_CACHE_DIR=.cache/finance_agent
STOCK_CACHE_TTL=3600
```

请勿提交包含真实密钥的 `.env` 文件。

### 多语言零样本意图分类器

意图分类默认使用 `MoritzLaurer/mDeBERTa-v3-base-mnli-xnli`。开发环境首次调用时
可由 Transformers 下载一次并缓存；生产镜像必须在构建或发布阶段预下载模型，
避免请求路径依赖外网。以下示例使用与运行时相同的缓存目录：

```python
from transformers import AutoModelForSequenceClassification, AutoTokenizer

model = "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"
cache_dir = ".cache/huggingface"
AutoTokenizer.from_pretrained(model, cache_dir=cache_dir)
AutoModelForSequenceClassification.from_pretrained(model, cache_dir=cache_dir)
```

`shadow` 模式保留分类 LLM 的结果作为主结果，并在后台记录零样本分类结果和延迟，
用于上线前对照。切换到 `zero_shot` 后，意图分类不再调用分类 LLM；模型加载或推理
异常会直接降级到确定性规则。生成式理财闲聊、槽位工具决策仍使用独立的聊天模型，
因此 API 请求与响应格式无需改变。设置为 `llm` 可显式只使用分类 LLM。

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

- API 服务：http://127.0.0.1:8000
- Swagger 文档：http://127.0.0.1:8000/docs
- ReDoc 文档：http://127.0.0.1:8000/redoc

### 6. 启动前端

打开另一个终端：

```bash
cd frontend
npm install
npm run dev
```

访问 http://localhost:5173。开发服务器会将 `/api` 请求代理至 `http://127.0.0.1:8000`。

## API 概览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/register` | 注册用户 |
| `POST` | `/api/login` | 登录并获取令牌 |
| `POST` | `/api/logout` | 注销当前令牌 |
| `GET` | `/api/me` | 获取当前用户信息 |
| `POST` | `/api/chat` | 同步投顾对话 |
| `POST` | `/api/chat/stream` | SSE 流式投顾对话 |
| `GET` | `/api/profile/{customer_id}` | 获取用户投资画像 |
| `GET` | `/api/history/{customer_id}` | 获取对话历史 |
| `POST` | `/api/conversations/{customer_id}` | 创建新会话 |
| `GET` | `/api/conversations/{customer_id}` | 获取会话列表 |
| `GET` | `/api/conversations/{customer_id}/{conversation_id}/messages` | 获取会话消息 |
| `DELETE` | `/api/conversations/{customer_id}/{conversation_id}` | 删除会话 |
| `POST` | `/api/reset/{customer_id}` | 重置用户会话 |
| `DELETE` | `/api/account` | 删除当前账户 |
| `GET` | `/api/health` | 服务健康检查 |

完整请求和响应结构请以 Swagger 文档为准。

### 对话示例

```bash
curl -X POST "http://127.0.0.1:8000/api/chat" \
  -H "Content-Type: application/json" \
  -H "X-Customer-ID: CUST001" \
  -d '{
    "message": "我有10万元，风险偏好稳健，想分析贵州茅台并给出配置建议",
    "customer_id": "CUST001",
    "chat_history": []
  }'
```

登录后也可以使用令牌：

```text
Authorization: Bearer <token>
```

系统解析客户身份时依次使用 Bearer Token、`X-Customer-ID` 请求头和请求体中的 `customer_id`。

## 常用开发命令

后端编译检查：

```bash
python -m compileall -q finance_agent
```

运行测试：

```bash
pytest
```

构建前端：

```bash
cd frontend
npm run build
```

## 数据与缓存

- BaoStock 数据默认缓存在 `.cache/finance_agent`，缓存时长由 `STOCK_CACHE_TTL` 控制。
- SQLite 默认数据库位于 `finance_agent/finance_agent.db`，可通过 `SQLITE_PATH` 修改。
- Redis 保存用户画像、滑动对话窗口和摘要等运行时记忆。
- BaoStock 提供的是最近交易日数据，并非交易所盘中实时行情。
