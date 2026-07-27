import json
import os
import subprocess
import sys


INTENT_ENV_NAMES = (
    "INTENT_CLASSIFIER_MODE",
    "INTENT_ZERO_SHOT_MODEL",
    "INTENT_MODEL_CACHE_DIR",
    "INTENT_MAX_LENGTH",
    "INTENT_SCORE_THRESHOLD",
    "INTENT_DEVICE",
)


def run_config(overrides):
    environment = os.environ.copy()
    for name in INTENT_ENV_NAMES:
        environment.pop(name, None)
    environment["DEEPSEEK_API_KEY"] = environment.get(
        "DEEPSEEK_API_KEY", "sk-test-config-only"
    )
    environment.update(overrides)
    script = """
import json
from finance_agent.config import (
    INTENT_CLASSIFIER_MODE,
    INTENT_DEVICE,
    INTENT_MAX_LENGTH,
    INTENT_SCORE_THRESHOLD,
    INTENT_ZERO_SHOT_MODEL,
)
print(json.dumps({
    "mode": INTENT_CLASSIFIER_MODE,
    "model": INTENT_ZERO_SHOT_MODEL,
    "max_length": INTENT_MAX_LENGTH,
    "threshold": INTENT_SCORE_THRESHOLD,
    "device": INTENT_DEVICE,
}))
"""
    output = subprocess.check_output(
        [sys.executable, "-c", script],
        env=environment,
        text=True,
    )
    return json.loads(output)


def test_invalid_intent_mode_defaults_to_shadow():
    result = run_config({"INTENT_CLASSIFIER_MODE": "bert"})
    assert result["mode"] == "shadow"


def test_zero_shot_defaults_are_production_safe():
    result = run_config({})
    assert result == {
        "mode": "shadow",
        "model": "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli",
        "max_length": 256,
        "threshold": 0.5,
        "device": -1,
    }
