import json
import os
from pathlib import Path
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
SQLITE_PATH = os.getenv(
    "SQLITE_PATH",
    str(Path(__file__).resolve().parent / "finance_agent.db"),
)

# ── 用户认证数据库（auth.db）────────────────────────────────────
# 独立于 checkpoint / 业务数据库，仅存储 users + sessions。
# 认证与图计算无关，保留传统 SQL 模型。
AUTH_DB_PATH = os.getenv(
    "AUTH_DB_PATH",
    str(Path(__file__).resolve().parent / "auth.db"),
)

# ── LangGraph Checkpoint（SqliteSaver）──────────────────────────
# 独立的 checkpoint 数据库，存储所有长期记忆：
#   - 对话状态（conversation_id 为 thread_id）
#   - 用户画像（profile:{customer_id} 为 thread_id）
#   - Agent 子图 checkpoint
CHECKPOINT_DB_PATH = os.getenv(
    "CHECKPOINT_DB_PATH",
    str(Path(__file__).resolve().parent / "checkpoint.db"),
)

# BaoStock 数据缓存；请求失败时可回退到最近一次成功缓存
STOCK_CACHE_DIR = os.getenv("STOCK_CACHE_DIR", ".cache/finance_agent")
STOCK_CACHE_TTL = int(os.getenv("STOCK_CACHE_TTL", "3600"))
BAOSTOCK_SOCKET_TIMEOUT = float(os.getenv("BAOSTOCK_SOCKET_TIMEOUT", "15"))

# 百度千帆智能搜索（行业/主题选股时使用）
QIANFAN_API_KEY = os.getenv("QIANFAN_API_KEY", "").strip()
QIANFAN_SEARCH_MODEL = os.getenv("QIANFAN_SEARCH_MODEL", "deepseek-v4-flash").strip()
QIANFAN_SEARCH_TIMEOUT = int(os.getenv("QIANFAN_SEARCH_TIMEOUT", "60"))
LLM_REQUEST_TIMEOUT = float(os.getenv("LLM_REQUEST_TIMEOUT", "45"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "1"))
FINAL_SYNTHESIS_TIMEOUT = float(os.getenv("FINAL_SYNTHESIS_TIMEOUT", "20"))
INTENT_MODEL = os.getenv("INTENT_MODEL", "deepseek:deepseek-v4-flash").strip()
INTENT_MODEL_TIMEOUT = float(os.getenv("INTENT_MODEL_TIMEOUT", "10"))
INTENT_MODEL_MAX_RETRIES = int(os.getenv("INTENT_MODEL_MAX_RETRIES", "1"))
INTENT_CLASSIFIER_MODE = os.getenv("INTENT_CLASSIFIER_MODE", "shadow").strip().lower()
if INTENT_CLASSIFIER_MODE not in {"shadow", "zero_shot", "llm"}:
    INTENT_CLASSIFIER_MODE = "shadow"
INTENT_ZERO_SHOT_MODEL = os.getenv(
    "INTENT_ZERO_SHOT_MODEL",
    "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli",
).strip()
INTENT_MODEL_CACHE_DIR = os.getenv("INTENT_MODEL_CACHE_DIR", "").strip()
INTENT_MAX_LENGTH = int(os.getenv("INTENT_MAX_LENGTH", "256"))
INTENT_SCORE_THRESHOLD = float(os.getenv("INTENT_SCORE_THRESHOLD", "0.5"))
INTENT_DEVICE = int(os.getenv("INTENT_DEVICE", "-1"))

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
    "supervisor": 0.2,        # 监督者：低温保证分类稳定
    "profile": 0.1,          # 画像抽取：低温保证抽取准确
    "slot_extraction": 0.1, # 画像与股票槽位：低温保证抽取准确
    "data_fetch": 0.0,        # 数据获取：零温度保证工具调用准确
    "fundamental": 0.3,      # 基本面分析：适度温度保证分析深度
    "allocation": 0.2,        # 资产配置：低温保证计算严谨
    "compliance": 0.0,        # 合规审查：零温度保证一致性
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


def get_intent_model():
    """返回兼容旧分类链的模型；新代码应分别使用分类器和闲聊模型。"""
    return init_chat_model(
        INTENT_MODEL,
        api_key=DEEPSEEK_API_KEY,
        temperature=0,
        timeout=INTENT_MODEL_TIMEOUT,
        max_retries=INTENT_MODEL_MAX_RETRIES,
    )


def get_supervisor_chat_model():
    """返回用于 Supervisor 理财闲聊生成的低成本模型。"""
    return get_intent_model()


# ── Checkpoint Saver ────────────────────────────────────────────

import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver

_checkpoint_saver: "SqliteSaver | None" = None
_checkpoint_conn: "sqlite3.Connection | None" = None
_checkpoint_lock = __import__("threading").Lock()


def get_checkpoint_saver() -> "SqliteSaver":
    """返回共享的 SqliteSaver 单例（线程安全，懒加载）。

    所有 Agent 子图和主编排图共享同一个 SqliteSaver 实例，
    以 conversation_id 作为 thread_id 实现对话级别的 checkpoint 隔离。

    SqliteSaver 内部连接使用 ``check_same_thread=False``，
    支持多线程并发访问。
    """
    global _checkpoint_saver, _checkpoint_conn
    if _checkpoint_saver is not None:
        return _checkpoint_saver
    with _checkpoint_lock:
        if _checkpoint_saver is not None:
            return _checkpoint_saver

        _checkpoint_conn = sqlite3.connect(
            CHECKPOINT_DB_PATH,
            check_same_thread=False,
        )
        _checkpoint_saver = SqliteSaver(_checkpoint_conn)
        _checkpoint_saver.setup()
        return _checkpoint_saver
