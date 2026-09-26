import os
from typing import Any
from dotenv import load_dotenv
from finance_agent.infrastructure.settings_models import (
    OrchestrationSettings,
    PostgresSettings,
    load_orchestration_settings,
    load_postgres_settings,
    settings_dump,
)

# 必须在 load_dotenv() 之前读取，确保 DeepSeek Key 只来自操作系统环境变量。
_SYSTEM_DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()

load_dotenv()

DEEPSEEK_API_KEY = _SYSTEM_DEEPSEEK_API_KEY
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_MEMORY_TTL_SECONDS = int(os.getenv("REDIS_MEMORY_TTL_SECONDS", "3600"))
# 已关闭匿名模式，所有业务请求必须携带有效 Bearer token。
AUTH_REQUIRED = True

# Environment/runtime hardening settings formerly held in the top-level config module.
UVICORN_HOST = os.getenv("UVICORN_HOST", "127.0.0.1").strip() or "127.0.0.1"
UVICORN_PORT = int(os.getenv("UVICORN_PORT", "8000"))
APP_ENV = os.getenv("APP_ENV", "development").strip().lower() or "development"
IS_PRODUCTION = APP_ENV in {"prod", "production"}
TRUST_PROXY = os.getenv("TRUST_PROXY", "false").strip().lower() in {"1", "true", "yes", "on"}
CORS_ALLOW_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ALLOW_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000",
    ).split(",")
    if origin.strip()
]
AUTH_RATE_LIMIT_ATTEMPTS = int(os.getenv("AUTH_RATE_LIMIT_ATTEMPTS", "8"))
AUTH_RATE_LIMIT_WINDOW_SECONDS = float(os.getenv("AUTH_RATE_LIMIT_WINDOW_SECONDS", "60"))

# LangGraph 混合编排预算（单轮最多扇出的领域数、合规一次改写、整图步数）。
# 默认值经 ``settings.OrchestrationSettings`` 校验（正/非负边界），此处保留同名
# 兼容常量，调用方与测试仍可直接取值或 monkeypatch。
_orchestration = load_orchestration_settings()
ORCHESTRATION_REACT_STEPS = _orchestration.react_steps
ORCHESTRATION_MAX_DOMAINS = _orchestration.max_domains
ORCHESTRATION_COMPLIANCE_REWRITES = _orchestration.compliance_rewrites
ORCHESTRATION_CLARIFY_ROUNDS = _orchestration.clarify_rounds
# 整图递归上限：领域专家已是 ReAct 子图（各自还有 6-10 步内部循环），追问环
# 还会再扇出一次重跑，32 步不足以覆盖嵌套子图开销。
ORCHESTRATION_GRAPH_STEPS = _orchestration.graph_steps

# 领域 ReAct 专家的分域步数预算（工具调用轮次）。细粒度工具包下，"多标的技术面
# 对比"需要多次取数+指标计算+收尾，stock 明显多于其它域；account/product
# 通常 2-4 次工具调用即可收敛。这些是**默认值**，硬上限另行校验（见 orchestration.budgets）。
EXPERT_STEPS_STOCK = int(os.getenv("EXPERT_STEPS_STOCK", "10"))
EXPERT_STEPS_PRODUCT = int(os.getenv("EXPERT_STEPS_PRODUCT", "6"))
EXPERT_STEPS_ACCOUNT = int(os.getenv("EXPERT_STEPS_ACCOUNT", "6"))
# 多域汇合节点的模型温度：仅组织表述、不重算数字，低温保证事实稳定。
SYNTHESIS_TEMPERATURE = float(os.getenv("SYNTHESIS_TEMPERATURE", "0.2"))
# 端到端墙钟预算。步数上限只约束"走了多少步"，管不住"某一步卡多久"：
# 一个挂住的取数或 LLM 调用能让单轮请求无限期不返回。因此除了步数，还需要
# **整轮**执行上限（图内强制，单领域与多领域共用）与 API/SSE 等待上限（外层）。
# 两者的大小关系由 ``OrchestrationSettings`` 校验：等待上限不得短于执行上限。
ORCHESTRATION_TURN_TIMEOUT = _orchestration.turn_timeout
ORCHESTRATION_TURN_DEADLINE = _orchestration.turn_deadline

# 板块/概念筛选的数据量预算（单一事实源，工具层不再自带默认值）：
# 每轮最多评估多少只板块成分、最终返回多少只候选。
ORCHESTRATION_SCREEN_MAX_EVALUATIONS = _orchestration.screen_max_evaluations
ORCHESTRATION_SCREEN_MAX_RESULTS = _orchestration.screen_max_results

# 最终答复的分块下发（SSE delta）。答案必须先经合规出口定稿，因此这里流的是
# **已通过校验**的文本，不是模型原始 token：合规校验的是完整草稿，边生成边推送
# 会让未校验内容直接落到用户界面。分块本身只影响呈现节奏，不改变内容与顺序。
ORCHESTRATION_STREAM_CHUNK_SIZE = _orchestration.stream_chunk_size
# 每块之间的停顿（毫秒）制造"逐字输出"的观感；为 0 时退化为一次推完。
ORCHESTRATION_STREAM_CHUNK_DELAY_MS = _orchestration.stream_chunk_delay_ms
# 分块下发的总时长上限（秒）：长报告按固定停顿会叠出数秒的额外等待，超出该
# 上限时自动压缩每块停顿，保证流式呈现只为观感、不为整体时延设障。
ORCHESTRATION_STREAM_MAX_SECONDS = _orchestration.stream_max_seconds

CELERY_REDIS_DB = int(os.getenv("CELERY_REDIS_DB", "1"))
CELERY_QUANT_QUEUE = os.getenv("CELERY_QUANT_QUEUE", "finance.quant").strip()
# 量化任务的软/硬超时与结果 TTL（秒）：CPU 计算不得无限占用 worker。
CELERY_TASK_SOFT_TIME_LIMIT = int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", "60"))
CELERY_TASK_HARD_TIME_LIMIT = int(os.getenv("CELERY_TASK_HARD_TIME_LIMIT", "120"))
CELERY_RESULT_EXPIRES = int(os.getenv("CELERY_RESULT_EXPIRES", "3600"))

# FAQ 检索阈值（实测校准，见 faq/retriever.py 注释）：
# - 绝对下限：低于该分视为知识库无可靠答案，返回 not_found。
#   中文短文本相似度天然偏高（无关内容可达 ~0.54），域内改写提问约 0.61~0.77，
#   因此取 0.57 作为“像不像一个问题”的最低分界。
# - 相对比例：只保留与最佳命中足够接近的候选（一问一答场景，弱相关应被甩开）。
#   定投查询里正确条目 0.82、弱相关条目 0.30，0.85 可稳定排除后者。

# 管理员 customer_id 白名单（逗号分隔）；用于限制管理接口（如清空全库记录）。
ADMIN_CUSTOMER_IDS = {
    cid.strip().upper()
    for cid in os.getenv("ADMIN_CUSTOMER_IDS", "").split(",")
    if cid.strip()
}

# ── PostgreSQL 存储 ─────────────────────────────────────
# 所有关系型数据、认证和 checkpoint 均使用 PostgreSQL。
# 连接/连接池参数经 ``settings.PostgresSettings`` 校验（端口格式、池上限不低于下限、
# 超时为正），此处保留同名兼容常量。
_postgres = load_postgres_settings()
POSTGRES_DSN = _postgres.dsn
POSTGRES_HOST = _postgres.host
POSTGRES_PORT = _postgres.port
POSTGRES_USER = _postgres.user
POSTGRES_PASSWORD = _postgres.password
POSTGRES_DB = _postgres.database
POSTGRES_CONNECT_TIMEOUT = _postgres.connect_timeout
# checkpoint 连接池容量。不同会话现在可并发执行，而每个 superstep 都会写
# checkpoint；psycopg_pool 在 max_size=None 时会把上限收敛为 min_size（默认 4），
# 超过该并发数的会话将在池上排队甚至超时，因此这里显式放开上限。
POSTGRES_POOL_MIN_SIZE = _postgres.pool_min_size
POSTGRES_POOL_MAX_SIZE = _postgres.pool_max_size
POSTGRES_POOL_TIMEOUT = _postgres.pool_timeout


def _postgres_dsn() -> str:
    """构建 PostgreSQL DSN；优先使用 POSTGRES_DSN。"""
    if POSTGRES_DSN:
        return POSTGRES_DSN
    if not POSTGRES_PASSWORD:
        raise RuntimeError("POSTGRES_PASSWORD 或 POSTGRES_DSN 必须配置")
    return f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"


def get_postgres_connection_factory():
    """返回 PostgreSQL 连接工厂；驱动缺失时显式失败。"""
    try:
        import psycopg  # type: ignore
    except ImportError as exc:
        raise RuntimeError("缺少 PostgreSQL 驱动，请安装 psycopg[binary]") from exc
    dsn = _postgres_dsn()
    return lambda: psycopg.connect(dsn, connect_timeout=POSTGRES_CONNECT_TIMEOUT)

# 统一股票数据源配置；Provider Manager 按顺序自动降级。
# 同花顺 Fuyao MCP：以 X-api-key 鉴权访问 fuyao.aicubes.cn 的四个 HTTP 端点。
FUYAO_API_KEY = os.getenv("FUYAO_API_KEY", "").strip()
FUYAO_MCP_BASE_URL = os.getenv("FUYAO_MCP_BASE_URL", "https://fuyao.aicubes.cn/mcp").strip()
FUYAO_MCP_TIMEOUT = float(os.getenv("FUYAO_MCP_TIMEOUT", "30"))
# 数据源守门：akshare/baostock 内部大量请求不设超时（实测 akshare 1290 处
# requests 调用仅 44 处带 timeout），一个挂住的 socket 会让整轮请求永久阻塞。
# 因此由 ProviderManager 在调用边界强制超时，并对连续失败的源做熔断，
# 避免已知故障源在每一轮请求里被重复尝试、把预算耗光。
DATA_PROVIDER_TIMEOUT = float(os.getenv("DATA_PROVIDER_TIMEOUT", "20"))
DATA_PROVIDER_FAILURE_THRESHOLD = int(os.getenv("DATA_PROVIDER_FAILURE_THRESHOLD", "3"))
DATA_PROVIDER_COOLDOWN = float(os.getenv("DATA_PROVIDER_COOLDOWN", "60"))
DEFAULT_DATA_PROVIDER = os.getenv("DEFAULT_DATA_PROVIDER", "akshare").strip().lower()
DATA_PROVIDER_ORDER = [
    item.strip().lower()
    for item in os.getenv(
        "DATA_PROVIDER_ORDER", "fuyao_mcp,akshare,baostock"
    ).split(",")
    if item.strip()
]
AKSHARE_ENABLED = os.getenv("AKSHARE_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
FUYAO_ENABLED = bool(FUYAO_API_KEY) and os.getenv("FUYAO_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
BAOSTOCK_ENABLED = os.getenv("BAOSTOCK_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
BAOSTOCK_USERNAME = os.getenv("BAOSTOCK_USERNAME", "").strip()
BAOSTOCK_PASSWORD = os.getenv("BAOSTOCK_PASSWORD", "").strip()

# 板块（概念/行业）取数：东财板块接口只挂在 *.push2.eastmoney.com 上，该域名在部分
# 网络环境（例如本机经系统代理）会连续数分钟 502/断连，因此这里显式给出**主机列表**
# 供轮换。改用环境变量还有两个用途：排障时可换成可达镜像；离线端到端测试可指向本地
# 打桩服务（`http://127.0.0.1:<port>`）。
EM_BOARD_BASE_URLS = os.getenv(
    "EM_BOARD_BASE_URLS",
    "https://17.push2.eastmoney.com,https://push2.eastmoney.com,https://79.push2.eastmoney.com",
).strip()
# 单请求超时 / 单个板块类型总预算（秒）。总预算必须显著小于 DATA_PROVIDER_TIMEOUT，
# 否则会先撞上 ProviderManager 的看门狗超时而拿不到"取数失败"的明确结论。
EM_BOARD_TIMEOUT = float(os.getenv("EM_BOARD_TIMEOUT", "4"))
EM_BOARD_DEADLINE = float(os.getenv("EM_BOARD_DEADLINE", "10"))
# 翻页上限：每页 100 行，8 页覆盖当前最大的概念板块表（约 500 行）。
EM_BOARD_MAX_PAGES = int(os.getenv("EM_BOARD_MAX_PAGES", "8"))
# 行情与估值的本地落盘缓存（最小版本，只覆盖 K 线与估值两条路径）。
# 默认锚定仓库根目录，避免随进程工作目录漂移；TTL 设为 0 表示关闭缓存。
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
QUOTE_CACHE_DIR = os.getenv(
    "QUOTE_CACHE_DIR", os.path.join(_PROJECT_ROOT, ".cache", "quotes")
).strip()
QUOTE_CACHE_TTL_SECONDS = int(os.getenv("QUOTE_CACHE_TTL_SECONDS", "3600"))

# DashScope 联网搜索已移除，板块/行业市场资料改用东方财富/新浪财经直接抓取
# 意图分类使用独立的轻量 Qwen 兼容接口；保留旧变量作为迁移期回退。
INTENT_MODEL_PROVIDER = os.getenv("INTENT_MODEL_PROVIDER", "qwen").strip().lower()
INTENT_MODEL = os.getenv("INTENT_MODEL", os.getenv("DEEPSEEK_INTENT_MODEL", "qwen-turbo")).strip()
INTENT_MODEL_BASE_URL = os.getenv(
    "INTENT_MODEL_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
).strip()
INTENT_MODEL_API_KEY = os.getenv(
    "INTENT_MODEL_API_KEY",
    os.getenv("QWEN_API_KEY", os.getenv("DASHSCOPE_API_KEY", "")),
).strip()
INTENT_MODEL_TIMEOUT = float(os.getenv("INTENT_MODEL_TIMEOUT", os.getenv("DEEPSEEK_INTENT_TIMEOUT", "5")))
INTENT_MODEL_MAX_RETRIES = int(os.getenv("INTENT_MODEL_MAX_RETRIES", os.getenv("DEEPSEEK_INTENT_MAX_RETRIES", "2")))
# 512 只够"intents + finance_related"；分类器现在还要在**同一次调用**里输出
# profile_facts（用户自述事实候选），输出被截断会让整轮路由变成协议错。
INTENT_MODEL_MAX_TOKENS = int(os.getenv("INTENT_MODEL_MAX_TOKENS", "800"))
INTENT_MODEL_DEADLINE = float(os.getenv("INTENT_MODEL_DEADLINE", "15"))
# 意图分类降级链：主模型不可用（超时/欠费/协议错）时自动回退到备用模型，
# 避免单一 provider 故障打断全部分类与路由。默认备用为 DeepSeek 兼容接口。
INTENT_FALLBACK_MODEL = os.getenv("INTENT_FALLBACK_MODEL", "deepseek-chat").strip()
INTENT_FALLBACK_BASE_URL = os.getenv(
    "INTENT_FALLBACK_BASE_URL", "https://api.deepseek.com/v1/chat/completions",
).strip()
INTENT_FALLBACK_API_KEY = os.getenv(
    "INTENT_FALLBACK_API_KEY", DEEPSEEK_API_KEY,
).strip()
INTENT_FALLBACK_TIMEOUT = float(os.getenv("INTENT_FALLBACK_TIMEOUT", "20"))
INTENT_FALLBACK_MAX_RETRIES = int(os.getenv("INTENT_FALLBACK_MAX_RETRIES", "1"))
# 与主模型同口径：输出里多了 profile_facts，512 容易被截断。
INTENT_FALLBACK_MAX_TOKENS = int(os.getenv("INTENT_FALLBACK_MAX_TOKENS", "800"))
INTENT_FALLBACK_DEADLINE = float(os.getenv("INTENT_FALLBACK_DEADLINE", "25"))
# 旧名称保留，避免未迁移调用方导入失败。
DEEPSEEK_INTENT_MODEL = INTENT_MODEL
DEEPSEEK_INTENT_TIMEOUT = INTENT_MODEL_TIMEOUT
DEEPSEEK_INTENT_MAX_RETRIES = INTENT_MODEL_MAX_RETRIES
LLM_REQUEST_TIMEOUT = float(os.getenv("LLM_REQUEST_TIMEOUT", "45"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "1"))
FINAL_SYNTHESIS_TIMEOUT = float(os.getenv("FINAL_SYNTHESIS_TIMEOUT", "20"))

# 政策事件解读的取数窗口与条数上限（天 / 条），避免解读上下文爆炸。
POLICY_NEWS_MAX_DAYS = int(os.getenv("POLICY_NEWS_MAX_DAYS", "3"))
POLICY_NEWS_MAX_ITEMS = int(os.getenv("POLICY_NEWS_MAX_ITEMS", "50"))

PRODUCT_ANALYSIS_TEMPERATURE = float(os.getenv("PRODUCT_ANALYSIS_TEMPERATURE", "0.2"))

# 产品研究的新鲜度阈值：超过阈值只披露来源与日期，不据此生成收益/比较结论。
PRODUCT_PERFORMANCE_FRESHNESS_DAYS = int(os.getenv("PRODUCT_PERFORMANCE_FRESHNESS_DAYS", "31"))
PRODUCT_HOLDINGS_FRESHNESS_DAYS = int(os.getenv("PRODUCT_HOLDINGS_FRESHNESS_DAYS", "120"))

# 资产配置测算假设（账户领域的"配置诊断/优化参考"）。
# 仓库无产品净值时序，无法求真实协方差，因此组合波动率采用对角（零相关）近似；
# 该假设会在响应里明示，不当作已校准的市场事实。

if not DEEPSEEK_API_KEY or DEEPSEEK_API_KEY == "sk-your-api-key-here":
    raise ValueError("请在操作系统环境变量中设置真实的 DEEPSEEK_API_KEY")

# ── PostgreSQL Checkpoint Saver ─────────────────────────────────

_checkpoint_saver: Any | None = None
_checkpoint_pool: Any | None = None
_checkpoint_lock = __import__("threading").Lock()


def get_checkpoint_saver():
    """返回共享的 PostgreSQL checkpoint saver，初始化失败时显式报错。"""
    global _checkpoint_saver, _checkpoint_pool
    if _checkpoint_saver is not None:
        return _checkpoint_saver
    with _checkpoint_lock:
        if _checkpoint_saver is not None:
            return _checkpoint_saver
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
            from psycopg_pool import ConnectionPool
        except ImportError as exc:
            raise RuntimeError(
                "缺少 PostgreSQL checkpoint 依赖，请安装 langgraph-checkpoint-postgres 和 psycopg-pool"
            ) from exc

        _checkpoint_pool = ConnectionPool(
            conninfo=_postgres_dsn(),
            kwargs={"autocommit": True, "connect_timeout": POSTGRES_CONNECT_TIMEOUT},
            min_size=POSTGRES_POOL_MIN_SIZE,
            max_size=POSTGRES_POOL_MAX_SIZE,
            timeout=POSTGRES_POOL_TIMEOUT,
            open=True,
        )
        try:
            _checkpoint_saver = PostgresSaver(_checkpoint_pool)
            _checkpoint_saver.setup()
        except Exception:
            _checkpoint_pool.close()
            _checkpoint_pool = None
            raise
        return _checkpoint_saver
