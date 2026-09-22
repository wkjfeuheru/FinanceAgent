import json
import os
from typing import Any
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model

# 必须在 load_dotenv() 之前读取，确保 DeepSeek Key 只来自操作系统环境变量。
_SYSTEM_DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()

def safe_parse_json(text: str, default: Any = None) -> Any:
    """Parse LLM JSON output with markdown-fence tolerance.

    支持 JSON 对象（dict）和 JSON 数组（list）。
    """
    if default is None:
        default = {}

    content = (text or "").strip()
    if "```json" in content:
        content = content.split("```json", 1)[1].split("```", 1)[0]
    elif "```" in content:
        parts = content.split("```")
        if len(parts) >= 2:
            content = parts[1]

    try:
        parsed: Any = json.loads(content.strip())
    except json.JSONDecodeError:
        return default

    if isinstance(parsed, (dict, list)):
        return parsed
    return default


load_dotenv()

DEEPSEEK_API_KEY = _SYSTEM_DEEPSEEK_API_KEY
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_MEMORY_TTL_SECONDS = int(os.getenv("REDIS_MEMORY_TTL_SECONDS", "3600"))
# 已关闭匿名模式，所有业务请求必须携带有效 Bearer token。
AUTH_REQUIRED = True

# LangGraph 混合编排预算（ReAct 四轮、计划八任务、两次重规划、合规一次改写、整图 32 步）。
ORCHESTRATION_REACT_STEPS = int(os.getenv("ORCHESTRATION_REACT_STEPS", "4"))
ORCHESTRATION_PLAN_TASKS = int(os.getenv("ORCHESTRATION_PLAN_TASKS", "8"))
ORCHESTRATION_REPLANS = int(os.getenv("ORCHESTRATION_REPLANS", "2"))
ORCHESTRATION_COMPLIANCE_REWRITES = int(os.getenv("ORCHESTRATION_COMPLIANCE_REWRITES", "1"))
ORCHESTRATION_GRAPH_STEPS = int(os.getenv("ORCHESTRATION_GRAPH_STEPS", "32"))
# 端到端墙钟预算。步数上限只约束"走了多少步"，管不住"某一步卡多久"：
# 一个挂住的取数或 LLM 调用能让单轮请求无限期不返回。因此除了步数，
# 还需要单轮整体上限（API 层）与计划执行上限（跨领域扇出循环）。
ORCHESTRATION_TURN_TIMEOUT = float(os.getenv("ORCHESTRATION_TURN_TIMEOUT", "180"))
ORCHESTRATION_PLAN_DEADLINE = float(os.getenv("ORCHESTRATION_PLAN_DEADLINE", "120"))

CELERY_REDIS_DB = int(os.getenv("CELERY_REDIS_DB", "1"))
CELERY_QUANT_QUEUE = os.getenv("CELERY_QUANT_QUEUE", "finance.quant").strip()
# 量化任务的软/硬超时与结果 TTL（秒）：CPU 计算不得无限占用 worker。
CELERY_TASK_SOFT_TIME_LIMIT = int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", "60"))
CELERY_TASK_HARD_TIME_LIMIT = int(os.getenv("CELERY_TASK_HARD_TIME_LIMIT", "120"))
CELERY_RESULT_EXPIRES = int(os.getenv("CELERY_RESULT_EXPIRES", "3600"))

FAQ_EMBEDDING_MODEL = os.getenv("FAQ_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5").strip()
FAQ_EMBEDDING_DEVICE = os.getenv("FAQ_EMBEDDING_DEVICE", "cpu").strip()
FAQ_EMBEDDING_MODEL_CACHE_DIR = os.getenv("FAQ_EMBEDDING_MODEL_CACHE_DIR", ".cache/models").strip()
# FAQ 检索阈值（实测校准，见 faq/retriever.py 注释）：
# - 绝对下限：低于该分视为知识库无可靠答案，返回 not_found。
#   中文短文本相似度天然偏高（无关内容可达 ~0.54），域内改写提问约 0.61~0.77，
#   因此取 0.57 作为“像不像一个问题”的最低分界。
# - 相对比例：只保留与最佳命中足够接近的候选（一问一答场景，弱相关应被甩开）。
#   定投查询里正确条目 0.82、弱相关条目 0.30，0.85 可稳定排除后者。
FAQ_MIN_SCORE = float(os.getenv("FAQ_MIN_SCORE", "0.57"))
FAQ_RELATIVE_SCORE_RATIO = float(os.getenv("FAQ_RELATIVE_SCORE_RATIO", "0.85"))

# 管理员 customer_id 白名单（逗号分隔）；用于限制管理接口（如清空全库记录）。
ADMIN_CUSTOMER_IDS = {
    cid.strip().upper()
    for cid in os.getenv("ADMIN_CUSTOMER_IDS", "").split(",")
    if cid.strip()
}

# ── PostgreSQL 存储 ─────────────────────────────────────
# 所有关系型数据、认证和 checkpoint 均使用 PostgreSQL。
POSTGRES_DSN = os.getenv("POSTGRES_DSN", "").strip()
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost").strip()
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432").strip()
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres").strip()
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "").strip()
POSTGRES_DB = os.getenv("POSTGRES_DB", "advisor").strip()
POSTGRES_CONNECT_TIMEOUT = float(os.getenv("POSTGRES_CONNECT_TIMEOUT", "10"))
# checkpoint 连接池容量。不同会话现在可并发执行，而每个 superstep 都会写
# checkpoint；psycopg_pool 在 max_size=None 时会把上限收敛为 min_size（默认 4），
# 超过该并发数的会话将在池上排队甚至超时，因此这里显式放开上限。
POSTGRES_POOL_MIN_SIZE = int(os.getenv("POSTGRES_POOL_MIN_SIZE", "4"))
POSTGRES_POOL_MAX_SIZE = int(os.getenv("POSTGRES_POOL_MAX_SIZE", "16"))
POSTGRES_POOL_TIMEOUT = float(os.getenv("POSTGRES_POOL_TIMEOUT", "30"))


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
TUSHARE_MCP_URL = os.getenv("TUSHARE_MCP_URL", "").strip()
TUSHARE_MCP_TIMEOUT = float(os.getenv("TUSHARE_MCP_TIMEOUT", "30"))
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
        "DATA_PROVIDER_ORDER", "akshare,tushare_mcp,baostock"
    ).split(",")
    if item.strip()
]
AKSHARE_ENABLED = os.getenv("AKSHARE_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
TUSHARE_ENABLED = bool(TUSHARE_MCP_URL) and os.getenv("TUSHARE_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
BAOSTOCK_ENABLED = os.getenv("BAOSTOCK_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
BAOSTOCK_USERNAME = os.getenv("BAOSTOCK_USERNAME", "").strip()
BAOSTOCK_PASSWORD = os.getenv("BAOSTOCK_PASSWORD", "").strip()
# 行情与估值的本地落盘缓存（最小版本，只覆盖 K 线与估值两条路径）。
# 默认锚定仓库根目录，避免随进程工作目录漂移；TTL 设为 0 表示关闭缓存。
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUOTE_CACHE_DIR = os.getenv(
    "QUOTE_CACHE_DIR", os.path.join(_PROJECT_ROOT, ".cache", "quotes")
).strip()
QUOTE_CACHE_TTL_SECONDS = int(os.getenv("QUOTE_CACHE_TTL_SECONDS", "3600"))
THEME_REFRESH_IDS = [
    item.strip() for item in os.getenv("THEME_REFRESH_IDS", "").split(",") if item.strip()
]
THEME_DISCOVERY_ENDPOINT = os.getenv("THEME_DISCOVERY_ENDPOINT", "").strip()
THEME_DISCOVERY_API_TOKEN = os.getenv("THEME_DISCOVERY_API_TOKEN", "").strip()
THEME_DISCOVERY_SOURCE_NAME = os.getenv("THEME_DISCOVERY_SOURCE_NAME", "外部主题分类服务").strip()
THEME_DISCOVERY_SOURCE_CLASS = os.getenv("THEME_DISCOVERY_SOURCE_CLASS", "licensed_classification").strip()
THEME_DISCOVERY_TIMEOUT = float(os.getenv("THEME_DISCOVERY_TIMEOUT", "15"))
THEME_DISCOVERY_IDS = [
    item.strip() for item in os.getenv("THEME_DISCOVERY_IDS", "").split(",") if item.strip()
]

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
INTENT_MODEL_MAX_TOKENS = int(os.getenv("INTENT_MODEL_MAX_TOKENS", "512"))
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
INTENT_FALLBACK_MAX_TOKENS = int(os.getenv("INTENT_FALLBACK_MAX_TOKENS", "512"))
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

# 模拟交易限额：充值有单笔上限，避免"账户收益"被随意注资稀释成无意义数字。
PORTFOLIO_MAX_DEPOSIT_AMOUNT = float(os.getenv("PORTFOLIO_MAX_DEPOSIT_AMOUNT", "10000000"))
PORTFOLIO_MIN_ORDER_AMOUNT = float(os.getenv("PORTFOLIO_MIN_ORDER_AMOUNT", "100"))

if not DEEPSEEK_API_KEY or DEEPSEEK_API_KEY == "sk-your-api-key-here":
    raise ValueError("请在操作系统环境变量中设置真实的 DEEPSEEK_API_KEY")

model = init_chat_model(
    "deepseek:deepseek-v4-pro",
    api_key=DEEPSEEK_API_KEY,
    timeout=LLM_REQUEST_TIMEOUT,
    max_retries=LLM_MAX_RETRIES,
)

# Agent 温度策略：不同任务使用不同温度
AGENT_TEMPERATURES = {
    "supervisor": 0.2,        # 总管：低温保证分类稳定
    "slot_extraction": 0.1, # 需求字段抽取：低温保证抽取准确
    "fundamental": 0.3,      # 基本面分析：适度温度保证分析深度
    "stock_analysis": 0.3,   # 股票综合分析：适度温度保证分析深度与决策灵活性
    "market_insight": 0.2,   # 市场洞察：低温保证市场级表述稳定（政策事件解读）
    "product_analysis": PRODUCT_ANALYSIS_TEMPERATURE,  # 产品解读
}


def get_model_for_agent(
    agent_name: str,
    *,
    timeout: float | None = None,
    max_retries: int | None = None,
):
    """根据 Agent 名称获取对应温度的模型实例。"""
    temperature = AGENT_TEMPERATURES.get(agent_name, 0.3)
    return init_chat_model(
        "deepseek:deepseek-v4-pro",
        api_key=DEEPSEEK_API_KEY,
        temperature=temperature,
        timeout=timeout if timeout is not None else LLM_REQUEST_TIMEOUT,
        max_retries=max_retries if max_retries is not None else LLM_MAX_RETRIES,
    )


def get_supervisor_model():
    """返回监督者用于工具决策与闲聊生成的轻量模型。"""
    return init_chat_model(
        "deepseek:deepseek-v4-flash",
        api_key=DEEPSEEK_API_KEY,
        temperature=0,
        timeout=LLM_REQUEST_TIMEOUT,
        max_retries=LLM_MAX_RETRIES,
    )


def get_intent_model(*, max_tokens: int | None = None):
    """返回意图分类/跨领域规划用的轻量 OpenAI 兼容模型。

    未配置 intent API key 时返回 ``None``，调用方必须回退到确定性实现。
    """
    if not INTENT_MODEL_API_KEY:
        return None
    base_url = INTENT_MODEL_BASE_URL
    for suffix in ("/chat/completions", "/completions", "/chat"):
        if base_url.endswith(suffix):
            base_url = base_url[: -len(suffix)]
            break
    return init_chat_model(
        f"openai:{INTENT_MODEL}",
        api_key=INTENT_MODEL_API_KEY,
        base_url=base_url,
        temperature=0,
        timeout=INTENT_MODEL_TIMEOUT,
        max_retries=INTENT_MODEL_MAX_RETRIES,
        max_tokens=max_tokens or INTENT_MODEL_MAX_TOKENS,
    )


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
