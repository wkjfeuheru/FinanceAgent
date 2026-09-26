"""提示词模板加载器：把 system prompt 从 Python 字符串外置为包内文本文件。

沿用仓库既有做法（``rule_engine.load_rules`` 以 ``Path(__file__)`` 读 ``rules/*.json``），
不引入 ``importlib.resources``：运行镜像直接 COPY 源码树，包内相对路径读取即可。
提示词放在 ``domains/<domain>/expert/prompts/`` 下，随 git 版本化，改动可审计。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

#: ``finance_agent/`` 包根目录（本文件位于 ``finance_agent/shared/prompts.py``）。
_PACKAGE_ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=None)
def load_prompt(relative_path: str) -> str:
    """读取包内提示词文件（路径相对 ``finance_agent/``）。

    内容按原文返回（保留首尾空行前的语义），不做 strip——提示词里的换行与
    缩进是有意的排版，交由模板文件自身决定。找不到文件时显式失败，避免
    静默加载到空提示词让专家无声退化。
    """
    path = _PACKAGE_ROOT / str(relative_path)
    if not path.is_file():
        raise FileNotFoundError(f"提示词文件不存在：{path}")
    return path.read_text(encoding="utf-8")


__all__ = ["load_prompt"]
