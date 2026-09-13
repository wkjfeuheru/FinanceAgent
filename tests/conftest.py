"""测试环境隔离。"""

import os
import shutil
import uuid
from pathlib import Path

import pytest

# config.py 在导入阶段要求存在 API Key；测试不应访问真实 LLM。
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")


@pytest.fixture(autouse=True)
def isolated_quote_cache(monkeypatch):
    """把行情缓存锚定到仓库内的临时目录，逐测试隔离。

    隔离是必需的：夹具行情以"今天"结尾，若读到上一次运行留下的缓存，
    新鲜度门禁会失效，测试结果随运行日期漂移。

    本环境有两条限制，因此这里既不用 ``tmp_path`` 也不用 ``tempfile.mkdtemp``：
    前者写系统临时目录会 ``PermissionError``；后者建出的目录**无法在其下再建子目录**
    （``WinError 5``，普通 ``mkdir`` 建的同级目录则正常）。仓库内路径可写，
    且 ``.cache/`` 已在 .gitignore 中。
    """
    from finance_agent import config

    base = Path(__file__).resolve().parent.parent / ".cache" / "test-quote-cache"
    cache_dir = base / f"case-{uuid.uuid4().hex[:8]}"
    cache_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "QUOTE_CACHE_DIR", str(cache_dir))
    yield
    shutil.rmtree(cache_dir, ignore_errors=True)


@pytest.fixture
def work_dir():
    """仓库内的临时目录，替代在本环境不可用的 ``tmp_path``。

    与 ``isolated_quote_cache`` 同样受限于：写系统临时目录会 ``PermissionError``，
    因此统一锚定到仓库内 ``.cache/test-work``（已在 .gitignore 中）。
    """
    base = Path(__file__).resolve().parent.parent / ".cache" / "test-work"
    path = base / f"case-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    yield path
    shutil.rmtree(path, ignore_errors=True)
