"""测试环境隔离。"""

import os
import shutil
import uuid
from pathlib import Path

import pytest

# Infrastructure settings require an API key at import time; tests use a fake key.
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
    from finance_agent.infrastructure import settings as config

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


# ── 领域专家的假 tool-calling 模型 ──────────────────────────────────────
# 专家是 LangGraph 原生 ``create_agent`` 工具循环，模型必须支持 ``bind_tools``
# 并能返回 ``tool_calls``。``GenericFakeChatModel`` 只实现了消息流，不实现
# ``bind_tools``，因此子类补上（返回自身，不真正绑定）。
_fake_chat_models = pytest.importorskip(
    "langchain_core.language_models.fake_chat_models",
    reason="需要 langchain_core 的假 chat 模型",
)


def make_fake_tool_model(messages):
    """构造一个可绑定工具、按序返回给定消息的假模型。

    ``messages`` 是 ``AIMessage`` 序列：带 ``tool_calls`` 的条目驱动工具循环，
    不带工具调用的条目作为最终答复。``iter`` 保证每轮消费一条。
    """
    from langchain_core.messages import AIMessage  # noqa: F401 - 供调用方构造

    base = _fake_chat_models.GenericFakeChatModel

    class _FakeToolModel(base):  # type: ignore[misc, valid-type]
        def bind_tools(self, tools, **kwargs):
            return self

    return _FakeToolModel(messages=iter(messages))


def tool_call(name: str, args: dict | None = None, call_id: str = "c1"):
    """构造一条发起工具调用的 AIMessage。"""
    from langchain_core.messages import AIMessage

    return AIMessage(
        content="",
        tool_calls=[{
            "name": name, "args": dict(args or {}), "id": call_id, "type": "tool_call",
        }],
    )


def final_message(text: str):
    """构造一条最终答复 AIMessage。"""
    from langchain_core.messages import AIMessage

    return AIMessage(content=text)


@pytest.fixture
def fake_tool_model():
    """把上面的工厂以 fixture 形式暴露，避免各测试文件重复定义假模型类。"""
    return make_fake_tool_model
