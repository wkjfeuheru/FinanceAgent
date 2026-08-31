"""测试环境隔离。"""

import os

# config.py 在导入阶段要求存在 API Key；测试不应访问真实 LLM。
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")
os.environ.setdefault("DEBATE_ENABLED", "false")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
