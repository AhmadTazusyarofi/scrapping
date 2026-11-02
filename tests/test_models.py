import dataclasses
from datetime import date

import pytest

from ihsg_screener.models import (
    Article,
    ArticleSentiment,
    Decision,
    ScanResult,
    SentimentLabel,
    SentimentVerdict,
    TechnicalSignal,
    Ticker,
)


def test_decision_memuat_seluruh_keputusan_spec():
    assert {d.value for d in Decision} == {
        "BUY_ALERT",
        "REJECTED_TECHNICAL",
        "REJECTED_SENTIMENT",
        "SKIPPED_NO_NEWS",
        "SKIPPED_DUPLICATE",
        "SKIPPED_NO_DATA",
        "ERROR",
    }


def test_sentiment_label_memuat_tiga_label():
    assert {s.value for s in SentimentLabel} == {"POSITIF", "NETRAL", "NEGATIF"}


@pytest.mark.parametrize(
    "cls",
    [Ticker, Article, TechnicalSignal, ArticleSentiment, SentimentVerdict, ScanResult],
)
def test_semua_dataclass_frozen(cls):
    assert dataclasses.fields(cls)
    assert cls.__dataclass_params__.frozen is True


def test_technical_signal_tidak_dapat_diubah():
    signal = TechnicalSignal(
        symbol="BBRI.JK",
        is_bullish=True,
        close=5000.0,
        as_of=date(2026, 8, 25),
        indicators={"sma_fast": 5010.0},
        passed_rules=("sma_cross",),
        failed_rules=(),
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        signal.close = 1.0


def test_scan_result_default_tanpa_teknikal_dan_sentimen():
    result = ScanResult(symbol="BBRI.JK", decision=Decision.ERROR, reason="uji")

    assert result.technical is None
    assert result.sentiment is None


def test_sentiment_verdict_menyimpan_hasil_per_artikel():
    article = Article(title="j", description="d", url="u", source="s", published_at="2026-08-25")
    item = ArticleSentiment(article=article, label=SentimentLabel.POSITIF, score=0.9)
    verdict = SentimentVerdict(
        label=SentimentLabel.POSITIF,
        score=0.9,
        analyzed_count=1,
        rejected_count=0,
        per_article=(item,),
    )

    assert verdict.per_article[0].article.title == "j"
