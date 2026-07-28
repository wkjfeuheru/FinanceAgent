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
SQLITE_PATH = os.getenv(
    "SQLITE_PATH",
    str(Path(__file__).resolve().parent / "finance_agent.db"),
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
    "stock_analysis": 0.3,   # 股票综合分析：适度温度保证分析深度与决策灵活性
    "allocation": 0.2,        # 资产配置：低温保证计算严谨
    "compliance": 0.0,        # 合规审查：零温度保证一致性
}


def get_model_for_agent(agent_name: str):
    """根据 Agent 名称获取对应温度的模型实例。"""
    temperature = AGENT_TEMPERATURES.get(agent_name, 0.3)
    return init_chat_model(
        "deepseek:deepseek-v4-pro",
        api_key=DEEPSEEK_API_KEY,
        temperature=temperature,
        timeout=LLM_REQUEST_TIMEOUT,
        max_retries=LLM_MAX_RETRIES,
    )
