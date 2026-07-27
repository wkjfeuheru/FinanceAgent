from finance_agent.agents.supervisor import (
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
        return {
            "sequence": sequence,
            "labels": ordered,
            "scores": [scores[label] for label in ordered],
        }


def label_scores(**internal_scores):
    return {
        candidate: internal_scores.get(intent, 0.01)
        for intent, candidate in CANDIDATE_LABELS.items()
    }


def input_text(message, context="", pending_allocation=False):
    if not context and not pending_allocation:
        return message
    return (
        f"[上下文] {context or '无'} [待补充配置] "
        f"{'是' if pending_allocation else '否'} [当前输入] {message}"
    )


def make_classifier(scores_by_sequence, **kwargs):
    fake = RecordingPipeline(scores_by_sequence)
    classifier = ZeroShotIntentClassifier(
        "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli",
        pipeline_factory=lambda _task, **_kwargs: fake,
        **kwargs,
    )
    return classifier, fake


def test_pipeline_receives_chinese_multilabel_contract():
    created = {}
    sequence = input_text("推荐银行股")
    fake = RecordingPipeline({
        sequence: label_scores(stock_recommendation=0.9),
    })

    def factory(task, **kwargs):
        created.update(task=task, **kwargs)
        return fake

    classifier = ZeroShotIntentClassifier(
        "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli",
        pipeline_factory=factory,
    )
    result = classifier.predict("推荐银行股")

    assert created == {
        "task": "zero-shot-classification",
        "model": "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli",
        "device": -1,
    }
    _, labels, options = fake.calls[0]
    assert labels == list(CANDIDATE_LABELS.values())
    assert options == {
        "multi_label": True,
        "hypothesis_template": "这段用户消息的意图是{}。",
        "truncation": True,
        "max_length": 256,
    }
    assert result["intents"][0]["intent"] == "stock_recommendation"


def test_plain_message_is_not_wrapped_when_context_is_absent():
    classifier, fake = make_classifier({
        "列出中际旭创的一些基本面指标": label_scores(market_query=0.9),
    })

    result = classifier.predict("列出中际旭创的一些基本面指标")

    assert fake.calls[0][0] == "列出中际旭创的一些基本面指标"
    assert result["intents"][0]["intent"] == "market_query"


def test_market_label_explicitly_covers_company_fundamentals():
    market_label = CANDIDATE_LABELS["market_query"]

    assert "财务" in market_label
    assert "估值" in market_label
    assert "业绩" in market_label
    assert "基本面指标" in market_label


def test_explicit_multi_intent_sentence_is_split():
    assert split_intent_queries("看看茅台走势，同时推荐两只银行股，然后配置10万元") == [
        "看看茅台走势",
        "推荐两只银行股",
        "配置10万元",
    ]


def test_matching_clauses_become_intent_queries():
    message = "看看茅台走势，同时推荐两只银行股"
    classifier, _ = make_classifier({
        input_text(message): label_scores(
            market_query=0.80,
            stock_recommendation=0.80,
        ),
        input_text("看看茅台走势"): label_scores(market_query=0.95),
        input_text("推荐两只银行股"): label_scores(stock_recommendation=0.96),
    })

    result = classifier.predict(message)

    by_intent = {item["intent"]: item for item in result["intents"]}
    assert by_intent["market_query"]["query"] == "看看茅台走势"
    assert by_intent["stock_recommendation"]["query"] == "推荐两只银行股"
    assert result["finance_related"] is True


def test_whole_message_match_falls_back_to_original_query():
    message = "分析茅台并判断是否值得买"
    classifier, _ = make_classifier({
        input_text(message): label_scores(
            market_query=0.90,
            stock_recommendation=0.92,
        ),
    })

    result = classifier.predict(message)

    assert {item["query"] for item in result["intents"]} == {message}


def test_matching_same_intent_clauses_are_merged():
    message = "看看茅台走势，同时查询宁德时代行情"
    classifier, _ = make_classifier({
        input_text(message): label_scores(market_query=0.80),
        input_text("看看茅台走势"): label_scores(market_query=0.91),
        input_text("查询宁德时代行情"): label_scores(market_query=0.93),
    })

    result = classifier.predict(message)

    assert result["intents"][0]["query"] == "看看茅台走势；查询宁德时代行情"


def test_non_financial_low_scores_are_not_finance_related():
    classifier, _ = make_classifier({
        input_text("写一首诗"): label_scores(),
    })

    result = classifier.predict("写一首诗")

    assert result["intents"] == []
    assert result["finance_related"] is False


def test_pipeline_cache_directory_is_forwarded_as_model_kwarg():
    created = {}
    fake = RecordingPipeline({input_text("聊聊投资心态"): label_scores(casual_chat=0.8)})

    def factory(task, **kwargs):
        created.update(task=task, **kwargs)
        return fake

    classifier = ZeroShotIntentClassifier(
        "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli",
        cache_dir=".cache/huggingface",
        pipeline_factory=factory,
    )
    classifier.predict("聊聊投资心态")

    assert created["model_kwargs"] == {"cache_dir": ".cache/huggingface"}
