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
# 旧名称保留，避免未迁移调用方导入失败。
DEEPSEEK_INTENT_MODEL = INTENT_MODEL
DEEPSEEK_INTENT_TIMEOUT = INTENT_MODEL_TIMEOUT
DEEPSEEK_INTENT_MAX_RETRIES = INTENT_MODEL_MAX_RETRIES
LLM_REQUEST_TIMEOUT = float(os.getenv("LLM_REQUEST_TIMEOUT", "45"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "1"))
FINAL_SYNTHESIS_TIMEOUT = float(os.getenv("FINAL_SYNTHESIS_TIMEOUT", "20"))

# 辩论流程配置：默认启用，并限制轮次与总耗时。
DEBATE_ENABLED = os.getenv("DEBATE_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
DEBATE_MAX_ROUNDS = int(os.getenv("DEBATE_MAX_ROUNDS", "2"))
DEBATE_TIMEOUT = float(os.getenv("DEBATE_TIMEOUT", "60.0"))
DEBATE_BULL_TEMPERATURE = float(os.getenv("DEBATE_BULL_TEMPERATURE", "0.4"))
DEBATE_BEAR_TEMPERATURE = float(os.getenv("DEBATE_BEAR_TEMPERATURE", "0.4"))
DEBATE_SYNTHESIS_TEMPERATURE = float(os.getenv("DEBATE_SYNTHESIS_TEMPERATURE", "0.1"))

PRODUCT_ANALYSIS_TEMPERATURE = float(os.getenv("PRODUCT_ANALYSIS_TEMPERATURE", "0.2"))

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
    "allocation": 0.2,        # 资产配置：低温保证计算严谨
    "debate_bull": DEBATE_BULL_TEMPERATURE,       # 看多分析
    "debate_bear": DEBATE_BEAR_TEMPERATURE,      # 看空分析
    "debate_synthesis": DEBATE_SYNTHESIS_TEMPERATURE,  # 辩论聚合
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
