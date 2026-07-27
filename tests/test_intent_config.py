import json
import os
import subprocess
import sys


RELEVANT_ENV_NAMES = (
    "INTENT_MODEL_CACHE_DIR",
    "INTENT_MAX_LENGTH",
    "INTENT_SCORE_THRESHOLD",
    "INTENT_DEVICE",
)


def run_config(overrides):
    environment = os.environ.copy()
    for name in RELEVANT_ENV_NAMES:
        environment.pop(name, None)
    environment["DEEPSEEK_API_KEY"] = environment.get(
        "DEEPSEEK_API_KEY", "sk-test-config-only"
    )
    environment.update(overrides)
    script = """
import json
import finance_agent.config as config
print(json.dumps({
    "cache_dir": config.INTENT_MODEL_CACHE_DIR,
    "max_length": config.INTENT_MAX_LENGTH,
    "threshold": config.INTENT_SCORE_THRESHOLD,
    "device": config.INTENT_DEVICE,
    "removed": {
        name: hasattr(config, name)
        for name in (
            "INTENT_CLASSIFIER_MODE", "INTENT_MODEL", "INTENT_MODEL_TIMEOUT",
            "INTENT_MODEL_MAX_RETRIES", "INTENT_ZERO_SHOT_MODEL",
        )
    },
}))
"""
    output = subprocess.check_output(
        [sys.executable, "-c", script], env=environment, text=True,
    )
    return json.loads(output)


def test_only_runtime_nli_settings_remain_configurable():
    result = run_config({
        "INTENT_MODEL_CACHE_DIR": "models/intent",
        "INTENT_MAX_LENGTH": "384",
        "INTENT_SCORE_THRESHOLD": "0.7",
        "INTENT_DEVICE": "1",
    })
    assert result == {
        "cache_dir": "models/intent",
        "max_length": 384,
        "threshold": 0.7,
        "device": 1,
        "removed": {
            "INTENT_CLASSIFIER_MODE": False,
            "INTENT_MODEL": False,
            "INTENT_MODEL_TIMEOUT": False,
            "INTENT_MODEL_MAX_RETRIES": False,
            "INTENT_ZERO_SHOT_MODEL": False,
        },
    }
