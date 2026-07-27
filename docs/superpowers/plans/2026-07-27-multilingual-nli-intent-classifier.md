# Multilingual NLI Intent Classifier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the custom-trained RoBERTa/ONNX intent runtime with `MoritzLaurer/mDeBERTa-v3-base-mnli-xnli` zero-shot multi-label classification while preserving workflow interfaces, rules, shadow evaluation, and generative chat.

**Architecture:** A focused `ZeroShotIntentClassifier` lazily constructs an injectable Transformers pipeline, classifies the whole message and independently split clauses, and maps descriptive Chinese candidate labels back to stable internal intent identifiers. `SupervisorAgent` selects LLM, shadow, or zero-shot operation; zero-shot failures go directly to deterministic rules and never to the classification LLM.

**Tech Stack:** Python 3.10+, Transformers `zero-shot-classification`, PyTorch CPU, LangChain, pytest.

## Global Constraints

- Runtime model is exactly `MoritzLaurer/mDeBERTa-v3-base-mnli-xnli` by default.
- Candidate labels are descriptive Chinese phrases and inference uses `multi_label=True` with `这段用户消息的意图是{}。`.
- Stable API intent names remain `market_query`, `stock_recommendation`, `asset_allocation`, and `casual_chat`.
- `INTENT_CLASSIFIER_MODE` accepts exactly `shadow`, `zero_shot`, or `llm`, defaulting to `shadow`.
- Zero-shot load or inference failure uses deterministic rules and does not call the classification LLM.
- Generative financial chat and slot-tool decisions continue to use the existing independent chat model.
- Production inference is CPU by default and production documentation requires model pre-download.
- Preserve unrelated changes in the dirty worktree; stage only files belonging to the current task.

---

### Task 1: Zero-shot classifier contract and clause aggregation

**Files:**
- Modify: `finance_agent/intent_classifier.py`
- Delete: `tests/test_bert_intent_classifier.py`
- Create: `tests/test_zero_shot_intent_classifier.py`

**Interfaces:**
- Produces: `ZeroShotIntentClassifier(model_name: str, max_length: int = 256, score_threshold: float = 0.5, device: int = -1, cache_dir: str | None = None, pipeline_factory: Callable[..., Any] | None = None)`.
- Produces: `ZeroShotIntentClassifier.predict(message: str, context: str = "", pending_allocation: bool = False) -> dict[str, Any]`.
- Preserves: `split_intent_queries(message: str) -> list[str]`.
- Returns: `{"intents": list[dict], "finance_related": bool, "latency_ms": float}`.

- [ ] **Step 1: Replace the BERT tests with failing zero-shot pipeline contract tests**

Create a recording fake whose `__call__` returns ordered `labels` and `scores`, then assert the constructor asks the factory for the correct task/model/device/cache and that prediction passes the exact Chinese candidates, `multi_label=True`, the Chinese hypothesis template, and `truncation=True` with `max_length=256`.

```python
from finance_agent.intent_classifier import (
    CANDIDATE_LABELS,
    ZeroShotIntentClassifier,
    split_intent_queries,
)


class RecordingPipeline:
    def __init__(self, scores_by_sequence):
        self.scores_by_sequence = scores_by_sequence
        self.calls = []

    def __call__(self, sequence, candidate_labels, **kwargs):
        self.calls.append((sequence, candidate_labels, kwargs))
        scores = self.scores_by_sequence[sequence]
        ordered = sorted(scores, key=scores.get, reverse=True)
        return {"sequence": sequence, "labels": ordered,
                "scores": [scores[label] for label in ordered]}


def test_pipeline_receives_chinese_multilabel_contract():
    created = {}
    fake = RecordingPipeline({
        "[上下文] 无 [待补充配置] 否 [当前输入] 推荐银行股": {
            label: 0.9 if "推荐股票" in label else 0.01
            for label in CANDIDATE_LABELS.values()
        }
    })

    def factory(task, **kwargs):
        created.update(task=task, **kwargs)
        return fake

    classifier = ZeroShotIntentClassifier(
        "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli",
        pipeline_factory=factory,
    )
    result = classifier.predict("推荐银行股")

    assert created["task"] == "zero-shot-classification"
    assert created["model"] == "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"
    _, labels, options = fake.calls[0]
    assert labels == list(CANDIDATE_LABELS.values())
    assert options == {
        "multi_label": True,
        "hypothesis_template": "这段用户消息的意图是{}。",
        "truncation": True,
        "max_length": 256,
    }
    assert result["intents"][0]["intent"] == "stock_recommendation"
```

- [ ] **Step 2: Run the contract test and confirm RED**

Run: `python -m pytest tests/test_zero_shot_intent_classifier.py::test_pipeline_receives_chinese_multilabel_contract -v`

Expected: FAIL because `CANDIDATE_LABELS` and `ZeroShotIntentClassifier` do not exist.

- [ ] **Step 3: Add failing aggregation and finance-boundary tests**

Add tests proving that `看看茅台走势，同时推荐两只银行股` attaches each matching clause to its own intent, duplicate clauses join with `；`, whole-message-only matches use the original message, and a low-scoring non-financial utterance returns `finance_related=False`.

```python
def test_matching_clauses_become_intent_queries():
    message = "看看茅台走势，同时推荐两只银行股"
    classifier = make_classifier({
        input_text(message): scores(market_query=.80, stock_recommendation=.80),
        input_text("看看茅台走势"): scores(market_query=.95),
        input_text("推荐两只银行股"): scores(stock_recommendation=.96),
    })
    result = classifier.predict(message)
    by_intent = {item["intent"]: item for item in result["intents"]}
    assert by_intent["market_query"]["query"] == "看看茅台走势"
    assert by_intent["stock_recommendation"]["query"] == "推荐两只银行股"
    assert result["finance_related"] is True


def test_non_financial_low_scores_are_not_finance_related():
    classifier = make_classifier({input_text("写一首诗"): scores()})
    result = classifier.predict("写一首诗")
    assert result["intents"] == []
    assert result["finance_related"] is False
```

- [ ] **Step 4: Run the new classifier test file and confirm RED**

Run: `python -m pytest tests/test_zero_shot_intent_classifier.py -v`

Expected: FAIL because zero-shot aggregation is not implemented.

- [ ] **Step 5: Implement the minimal zero-shot classifier**

Replace ONNX-specific imports, metadata, sigmoid, and session handling with:

```python
CANDIDATE_LABELS = {
    "market_query": "查询股票、指数、板块或市场行情",
    "stock_recommendation": "推荐股票或判断某只股票是否值得买入",
    "asset_allocation": "根据金额、期限和风险偏好制定资产配置方案",
    "casual_chat": "一般理财知识、投资心态或非任务型金融交流",
}
HYPOTHESIS_TEMPLATE = "这段用户消息的意图是{}。"


class ZeroShotIntentClassifier:
    def __init__(self, model_name, max_length=256, score_threshold=0.5,
                 device=-1, cache_dir=None, pipeline_factory=None):
        self.model_name = model_name
        self.max_length = max_length
        self.score_threshold = score_threshold
        self.device = device
        self.cache_dir = cache_dir or None
        self._pipeline_factory = pipeline_factory
        self._pipeline = None

    def _load(self):
        if self._pipeline is None:
            if self._pipeline_factory is None:
                from transformers import pipeline
                self._pipeline_factory = pipeline
            kwargs = {"model": self.model_name, "device": self.device}
            if self.cache_dir:
                kwargs["model_kwargs"] = {"cache_dir": self.cache_dir}
            self._pipeline = self._pipeline_factory("zero-shot-classification", **kwargs)

    @staticmethod
    def _input_text(message, context, pending_allocation):
        return (f"[上下文] {context or '无'} [待补充配置] "
                f"{'是' if pending_allocation else '否'} [当前输入] {message}")
```

Implement `_scores()` by converting returned Chinese labels to internal identifiers. Implement `predict()` using the existing clause merge behavior and set `finance_related` when any business intent passes threshold or the input matches existing financial terms. Every model-generated item uses reason `多语言 NLI 零样本分类`.

- [ ] **Step 6: Run classifier tests and confirm GREEN**

Run: `python -m pytest tests/test_zero_shot_intent_classifier.py -v`

Expected: all tests PASS without downloading a model.

- [ ] **Step 7: Commit the focused classifier change**

```bash
git add finance_agent/intent_classifier.py tests/test_zero_shot_intent_classifier.py tests/test_bert_intent_classifier.py
git commit -m "feat: add multilingual zero-shot intent classifier"
```

### Task 2: Supervisor modes, shadow logging, and rule fallback

**Files:**
- Modify: `finance_agent/agents/supervisor.py`
- Modify: `tests/test_zero_shot_intent_classifier.py`
- Modify: `tests/test_supervisor_multi_intent.py`

**Interfaces:**
- Consumes: `ZeroShotIntentClassifier.predict(...)` from Task 1.
- Produces: lazy `SupervisorAgent.zero_shot_classifier` property.
- Produces: `_predict_zero_shot(message, context, pending_allocation) -> dict[str, Any]`.
- Preserves: `classify_intents(...)`, `plan_tasks(...)`, and API result schema.

- [ ] **Step 1: Add failing Supervisor mode tests**

```python
def test_zero_shot_mode_does_not_invoke_llm(monkeypatch):
    agent = object.__new__(SupervisorAgent)
    agent._zero_shot_classifier = FakeZeroShotClassifier({
        "推荐银行股": {"stock_recommendation": .9}
    })
    agent._intent_chain = ExplodingChain()
    monkeypatch.setattr(supervisor_module, "INTENT_CLASSIFIER_MODE", "zero_shot")
    result = agent.plan_tasks("推荐银行股")
    assert [item["intent"] for item in result["intents"]] == ["stock_recommendation"]
    assert result["intent_source"] in {"zero_shot", "zero_shot+rule"}


def test_zero_shot_failure_uses_rules_without_llm(monkeypatch):
    agent = object.__new__(SupervisorAgent)
    agent._zero_shot_classifier = BrokenClassifier()
    agent._intent_chain = ExplodingChain()
    monkeypatch.setattr(supervisor_module, "INTENT_CLASSIFIER_MODE", "zero_shot")
    result = agent.plan_tasks("推荐三只银行股，用10万元做稳健配置")
    assert {item["intent"] for item in result["intents"]} == {
        "stock_recommendation", "asset_allocation"
    }
    assert result["intent_source"] == "rule_fallback"
```

Also add a shadow-mode test that waits on a synchronous fake executor and verifies the LLM result remains primary while `_predict_zero_shot` is called only for logging.

- [ ] **Step 2: Run the Supervisor tests and confirm RED**

Run: `python -m pytest tests/test_zero_shot_intent_classifier.py tests/test_supervisor_multi_intent.py -v`

Expected: FAIL because Supervisor still accepts `bert` and exposes BERT-named members and sources.

- [ ] **Step 3: Rewire Supervisor to zero-shot naming and semantics**

Update imports and members:

```python
from finance_agent.intent_classifier import ZeroShotIntentClassifier

self._zero_shot_classifier = None

@property
def zero_shot_classifier(self) -> ZeroShotIntentClassifier:
    if self._zero_shot_classifier is None:
        self._zero_shot_classifier = ZeroShotIntentClassifier(
            INTENT_ZERO_SHOT_MODEL,
            max_length=INTENT_MAX_LENGTH,
            score_threshold=INTENT_SCORE_THRESHOLD,
            device=INTENT_DEVICE,
            cache_dir=INTENT_MODEL_CACHE_DIR,
        )
    return self._zero_shot_classifier
```

Rename `_predict_bert` to `_predict_zero_shot`, update shadow log fields to retain generic `shadow_labels`/`shadow_latency_ms`, and make `classify_intents` select these branches explicitly:

```python
if INTENT_CLASSIFIER_MODE == "zero_shot":
    try:
        parsed = self._predict_zero_shot(message, context, pending_allocation)
        source = "zero_shot"
    except Exception as exc:
        _LOGGER.warning("intent_zero_shot_unavailable error=%s", exc)
        parsed = {}
        source = "rule_fallback"
else:
    parsed = self._classify_with_llm(...)
```

When deterministic rules add a new intent, change the source only from `zero_shot` to `zero_shot+rule`; preserve `rule_fallback` on total model failure. Keep `get_intent_model()` for LLM compatibility, chat generation, and slot tool calls.

- [ ] **Step 4: Run targeted Supervisor tests and confirm GREEN**

Run: `python -m pytest tests/test_zero_shot_intent_classifier.py tests/test_supervisor_multi_intent.py -v`

Expected: all tests PASS.

- [ ] **Step 5: Run workflow regression tests**

Run: `python -m pytest tests/test_multi_intent_workflow.py tests/test_slot_tool_routing.py tests/test_market_search_routing.py -v`

Expected: all tests PASS and no assertion expects `bert` sources.

- [ ] **Step 6: Commit Supervisor integration**

```bash
git add finance_agent/agents/supervisor.py tests/test_zero_shot_intent_classifier.py tests/test_supervisor_multi_intent.py
git commit -m "feat: route supervisor intents through multilingual NLI"
```

### Task 3: Configuration and dependency cleanup

**Files:**
- Modify: `finance_agent/config.py`
- Modify: `pyproject.toml`
- Modify: `requirements.txt`
- Modify: `.gitignore`
- Create: `tests/test_intent_config.py`

**Interfaces:**
- Produces: `INTENT_ZERO_SHOT_MODEL: str`, `INTENT_MODEL_CACHE_DIR: str`, `INTENT_MAX_LENGTH: int`, `INTENT_SCORE_THRESHOLD: float`, and `INTENT_DEVICE: int`.
- Removes: `INTENT_MODEL_DIR`, `INTENT_ONNX_THREADS`, and `intent-train` extras.

- [ ] **Step 1: Add failing configuration tests in an isolated subprocess**

Use a subprocess so environment-backed module constants are reloaded reliably:

```python
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
```

The helper must pass the existing `DEEPSEEK_API_KEY` into the subprocess and print only a JSON object containing these constants.

- [ ] **Step 2: Run config tests and confirm RED**

Run: `python -m pytest tests/test_intent_config.py -v`

Expected: FAIL because the zero-shot configuration constants do not exist and `bert` is still accepted.

- [ ] **Step 3: Implement new configuration constants**

```python
INTENT_CLASSIFIER_MODE = os.getenv("INTENT_CLASSIFIER_MODE", "shadow").strip().lower()
if INTENT_CLASSIFIER_MODE not in {"shadow", "zero_shot", "llm"}:
    INTENT_CLASSIFIER_MODE = "shadow"
INTENT_ZERO_SHOT_MODEL = os.getenv(
    "INTENT_ZERO_SHOT_MODEL",
    "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli",
).strip()
INTENT_MODEL_CACHE_DIR = os.getenv("INTENT_MODEL_CACHE_DIR", "").strip()
INTENT_MAX_LENGTH = int(os.getenv("INTENT_MAX_LENGTH", "256"))
INTENT_SCORE_THRESHOLD = float(os.getenv("INTENT_SCORE_THRESHOLD", "0.5"))
INTENT_DEVICE = int(os.getenv("INTENT_DEVICE", "-1"))
```

Remove ONNX Runtime from both dependency files. Add `torch>=2.2` to runtime dependencies because Transformers NLI inference requires a backend. Remove the `intent-train` optional dependency block. Replace old model output ignores with only the project-local Hugging Face cache directory if the docs choose one, such as `.cache/huggingface/`.

- [ ] **Step 4: Run configuration and import tests**

Run: `python -m pytest tests/test_intent_config.py tests/test_zero_shot_intent_classifier.py -v`

Expected: all tests PASS.

- [ ] **Step 5: Verify no runtime ONNX or old config references remain**

Run: `rg -n "onnxruntime|INTENT_MODEL_DIR|INTENT_ONNX_THREADS|intent-train|BertIntentClassifier" finance_agent tests pyproject.toml requirements.txt .gitignore`

Expected: no matches.

- [ ] **Step 6: Commit configuration and dependencies**

```bash
git add finance_agent/config.py pyproject.toml requirements.txt .gitignore tests/test_intent_config.py
git commit -m "chore: configure multilingual NLI runtime"
```

### Task 4: Remove custom training and obsolete evaluation scripts

**Files:**
- Delete: `scripts/train_intent_classifier.py`
- Delete: `scripts/generate_intent_dataset.py`
- Delete: `scripts/finalize_pending_intent_dataset.py`
- Delete: `scripts/evaluate_intent_shadow.py`
- Create: `tests/test_no_legacy_intent_training.py`

**Interfaces:**
- Removes all repository-owned entry points for custom intent data generation, fine-tuning, calibration, ONNX export, and old shadow-log evaluation.
- Does not delete untracked user datasets or model artifacts.

- [ ] **Step 1: Add a failing legacy-removal test**

```python
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
```

- [ ] **Step 2: Run the removal test and confirm RED**

Run: `python -m pytest tests/test_no_legacy_intent_training.py -v`

Expected: FAIL listing the four existing scripts.

- [ ] **Step 3: Delete only the four tracked/untracked repository scripts**

Use `apply_patch` deletion for the exact files listed above. Do not recursively remove `scripts/`, `data/`, `.cache/`, or `finance_agent/models/`.

- [ ] **Step 4: Run the removal test and repository search**

Run: `python -m pytest tests/test_no_legacy_intent_training.py -v`

Expected: PASS.

Run: `rg -n "chinese-roberta-wwm-ext|torch\.onnx\.export|model\.onnx|intent_config\.json" . -g "!docs/superpowers/**" -g "!.git/**"`

Expected: no matches in application, tests, scripts, or active documentation.

- [ ] **Step 5: Commit legacy pipeline removal**

```bash
git add scripts tests/test_no_legacy_intent_training.py
git commit -m "chore: remove custom RoBERTa training pipeline"
```

### Task 5: Deployment documentation and complete regression verification

**Files:**
- Modify: `README.md`
- Test: all files under `tests/`

**Interfaces:**
- Documents local development download behavior and production pre-download/cached loading.
- Documents `shadow` evaluation and the switch to `zero_shot` without changing chat API payloads.

- [ ] **Step 1: Replace README RoBERTa training instructions**

Document these exact environment variables:

```dotenv
INTENT_CLASSIFIER_MODE=shadow
INTENT_ZERO_SHOT_MODEL=MoritzLaurer/mDeBERTa-v3-base-mnli-xnli
INTENT_MODEL_CACHE_DIR=.cache/huggingface
INTENT_MAX_LENGTH=256
INTENT_SCORE_THRESHOLD=0.5
INTENT_DEVICE=-1
```

Add a production pre-download example that uses Transformers APIs and the same cache directory:

```python
from transformers import AutoModelForSequenceClassification, AutoTokenizer

model = "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"
cache_dir = ".cache/huggingface"
AutoTokenizer.from_pretrained(model, cache_dir=cache_dir)
AutoModelForSequenceClassification.from_pretrained(model, cache_dir=cache_dir)
```

Explain that development may download once on first use, production images must pre-download during build/release, `shadow` keeps LLM output primary, and `zero_shot` stops classification LLM calls. State that model exceptions degrade to deterministic rules.

- [ ] **Step 2: Check active docs for obsolete commands and names**

Run: `rg -n "train_intent_classifier|generate_intent_dataset|finalize_pending_intent_dataset|evaluate_intent_shadow|INTENT_MODEL_DIR|INTENT_ONNX_THREADS|INTENT_CLASSIFIER_MODE=bert" README.md finance_agent tests scripts pyproject.toml requirements.txt`

Expected: no matches.

- [ ] **Step 3: Run targeted intent and workflow tests**

Run: `python -m pytest tests/test_zero_shot_intent_classifier.py tests/test_intent_config.py tests/test_no_legacy_intent_training.py tests/test_supervisor_multi_intent.py tests/test_multi_intent_workflow.py tests/test_slot_tool_routing.py tests/test_market_search_routing.py -v`

Expected: all tests PASS without network access or real model download.

- [ ] **Step 4: Run the complete backend test suite**

Run: `python -m pytest -v`

Expected: all tests PASS. If pre-existing failures occur, record exact failures and prove they reproduce without the task changes before classifying them as unrelated.

- [ ] **Step 5: Run syntax and legacy-reference verification**

Run: `python -m compileall -q finance_agent tests`

Expected: exit code 0.

Run: `rg -n "BertIntentClassifier|_bert_classifier|_predict_bert|bert\+rule|onnxruntime|chinese-roberta-wwm-ext|model\.onnx" finance_agent tests scripts README.md pyproject.toml requirements.txt .gitignore`

Expected: no matches.

- [ ] **Step 6: Optionally run the real-model smoke check in a prepared environment**

This is an explicit network/cache-dependent check and is not part of the default test suite:

```powershell
$env:INTENT_CLASSIFIER_MODE='zero_shot'
python -c "from finance_agent.intent_classifier import ZeroShotIntentClassifier; c=ZeroShotIntentClassifier('MoritzLaurer/mDeBERTa-v3-base-mnli-xnli'); print(c.predict('分析茅台走势并判断是否值得买'))"
```

Expected: the returned intent names include `market_query` and `stock_recommendation`. If the model is not already cached, obtain user approval before allowing the download.

- [ ] **Step 7: Commit documentation and final verification state**

```bash
git add README.md
git commit -m "docs: document zero-shot intent deployment"
```

