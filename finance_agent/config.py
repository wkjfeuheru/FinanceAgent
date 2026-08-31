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

# ── PostgreSQL 存储（必需）─────────────────────────────────────
# 所有关系型数据、认证和 checkpoint 均使用 PostgreSQL。
POSTGRES_DSN = os.getenv("POSTGRES_DSN", "").strip()
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost").strip()
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432").strip()
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres").strip()
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "").strip()
POSTGRES_DB = os.getenv("POSTGRES_DB", "advisor").strip()


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
    return lambda: psycopg.connect(dsn)

# Tushare MCP 数据缓存；请求失败时可回退到最近一次成功缓存
TUSHARE_MCP_URL = os.getenv("TUSHARE_MCP_URL", "").strip()
TUSHARE_MCP_TIMEOUT = float(os.getenv("TUSHARE_MCP_TIMEOUT", "30"))

# DashScope 联网搜索已移除，板块/行业市场资料改用东方财富/新浪财经直接抓取
DEEPSEEK_INTENT_MODEL = os.getenv("DEEPSEEK_INTENT_MODEL", "deepseek-chat").strip()
DEEPSEEK_INTENT_TIMEOUT = float(os.getenv("DEEPSEEK_INTENT_TIMEOUT", "30"))
DEEPSEEK_INTENT_MAX_RETRIES = int(os.getenv("DEEPSEEK_INTENT_MAX_RETRIES", "1"))
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

        _checkpoint_pool = ConnectionPool(conninfo=_postgres_dsn(), open=True)
        _checkpoint_saver = PostgresSaver(_checkpoint_pool)
        _checkpoint_saver.setup()
        return _checkpoint_saver
