import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
DEEPSEEK_INTENT_ENV_NAMES = (
    "DEEPSEEK_INTENT_MODEL",
    "DEEPSEEK_INTENT_TIMEOUT",
    "DEEPSEEK_INTENT_MAX_RETRIES",
)


def run_config(overrides):
    environment = os.environ.copy()
    for name in DEEPSEEK_INTENT_ENV_NAMES:
        environment.pop(name, None)
    environment["DEEPSEEK_API_KEY"] = environment.get(
        "DEEPSEEK_API_KEY", "sk-test-config-only"
    )
    environment.update(overrides)
    script = """
import json
import finance_agent.config as config
print(json.dumps({
    "api_key": "test-deepseek",
    
    "model": config.DEEPSEEK_INTENT_MODEL,
    "timeout": config.DEEPSEEK_INTENT_TIMEOUT,
    "max_retries": config.DEEPSEEK_INTENT_MAX_RETRIES,
    "legacy": {
        name: hasattr(config, name)
        for name in (
            "INTENT_MODEL_CACHE_DIR", "INTENT_MAX_LENGTH",
            "INTENT_SCORE_THRESHOLD", "INTENT_DEVICE",
        )
    },
}))
"""
    output = subprocess.check_output(
        [sys.executable, "-c", script], env=environment, text=True,
    )
    return json.loads(output)


def test_deepseek_intent_settings_are_configurable_and_nli_settings_are_removed():
    result = run_config({
        "DEEPSEEK_API_KEY": "test-deepseek",
        
        "DEEPSEEK_INTENT_MODEL": "deepseek-test",
        "DEEPSEEK_INTENT_TIMEOUT": "12.5",
        "DEEPSEEK_INTENT_MAX_RETRIES": "2",
    })

    assert result == {
        "api_key": "test-deepseek",
        
        "model": "deepseek-test",
        "timeout": 12.5,
        "max_retries": 2,
        "legacy": {
            "INTENT_MODEL_CACHE_DIR": False,
            "INTENT_MAX_LENGTH": False,
            "INTENT_SCORE_THRESHOLD": False,
            "INTENT_DEVICE": False,
        },
    }


def test_local_nli_runtime_dependencies_are_removed():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    for dependency in ("transformers", "torch"):
        assert dependency not in requirements.lower()
        assert dependency not in pyproject.lower()


def test_production_source_has_no_local_nli_classifier():
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "finance_agent").rglob("*.py")
    )

    assert "ZeroShotIntentClassifier" not in source
    assert "mDeBERTa" not in source
