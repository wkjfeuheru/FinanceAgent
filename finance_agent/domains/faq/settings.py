"""FAQ-domain model and retrieval settings sourced from environment values."""

import os
from dotenv import dotenv_values

_DOTENV_VALUES = dotenv_values()


def _domain_env(name: str, default: str) -> str:
    if name in os.environ:
        return os.environ[name]
    value = _DOTENV_VALUES.get(name)
    return default if value is None else value


FAQ_EMBEDDING_MODEL = _domain_env("FAQ_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5").strip()
FAQ_EMBEDDING_DEVICE = _domain_env("FAQ_EMBEDDING_DEVICE", "cpu").strip()
FAQ_EMBEDDING_MODEL_CACHE_DIR = _domain_env("FAQ_EMBEDDING_MODEL_CACHE_DIR", ".cache/models").strip()
FAQ_MIN_SCORE = float(_domain_env("FAQ_MIN_SCORE", "0.57"))
FAQ_RELATIVE_SCORE_RATIO = float(_domain_env("FAQ_RELATIVE_SCORE_RATIO", "0.85"))
