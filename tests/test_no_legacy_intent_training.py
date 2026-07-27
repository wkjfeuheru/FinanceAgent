from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_custom_roberta_training_pipeline_is_removed():
    removed = [
        "scripts/train_intent_classifier.py",
        "scripts/generate_intent_dataset.py",
        "scripts/finalize_pending_intent_dataset.py",
        "scripts/evaluate_intent_shadow.py",
    ]
    assert all(not (ROOT / path).exists() for path in removed)
