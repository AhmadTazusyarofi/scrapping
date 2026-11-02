import dataclasses

import pytest

from ihsg_screener.config import SentimentConfig
from ihsg_screener.core import sentiment
from ihsg_screener.models import Article, ArticleSentiment, SentimentLabel

CFG = SentimentConfig(
    model="m",
    articles_per_ticker=3,
    min_articles=1,
    min_avg_score=0.60,
    neutral_weight=0.0,
    veto_on_strong_negative=True,
    strong_negative_threshold=0.80,
    batch_size=8,
)


def _artikel(i=0):
    return Article(
        title=f"judul {i}", description="", url=f"u{i}", source="s",
        published_at="2026-08-25T00:00:00Z",
    )


def _hasil(*pasangan):
    return [
        ArticleSentiment(article=_artikel(i), label=label, score=score)
        for i, (label, score) in enumerate(pasangan)
    ]


def test_positif_kuat_menghasilkan_verdict_positif():
    verdict = sentiment.aggregate(
        _hasil((SentimentLabel.POSITIF, 0.9), (SentimentLabel.POSITIF, 0.8)), CFG
    )

    assert verdict.label is SentimentLabel.POSITIF
    assert verdict.score == pytest.approx(0.85)
    assert verdict.analyzed_count == 2


def test_positif_lemah_di_bawah_ambang_menghasilkan_netral():
    verdict = sentiment.aggregate(_hasil((SentimentLabel.POSITIF, 0.55)), CFG)

    assert verdict.label is SentimentLabel.NETRAL


def test_netral_menyumbang_nol_secara_bawaan():
    verdict = sentiment.aggregate(
        _hasil((SentimentLabel.POSITIF, 0.9), (SentimentLabel.NETRAL, 0.9)), CFG
    )

    assert verdict.score == pytest.approx(0.45)
    assert verdict.label is SentimentLabel.NETRAL


def test_negatif_kuat_memveto_meski_ada_dua_positif():
    verdict = sentiment.aggregate(
        _hasil(
            (SentimentLabel.POSITIF, 0.9),
            (SentimentLabel.POSITIF, 0.9),
            (SentimentLabel.NEGATIF, 0.85),
        ),
        CFG,
    )

    assert verdict.label is SentimentLabel.NEGATIF


# Rata-rata berbobotnya 0.622, di atas ambang 0.60, sehingga label akhirnya
# ditentukan murni oleh veto: satu artikel negatif berkeyakinan 0.85.
_VETO_MENENTUKAN = (
    (SentimentLabel.POSITIF, 0.99),
    (SentimentLabel.POSITIF, 0.99),
    (SentimentLabel.POSITIF, 0.99),
    (SentimentLabel.POSITIF, 0.99),
    (SentimentLabel.NEGATIF, 0.85),
)


def test_veto_aktif_mengalahkan_rata_rata_yang_lolos_ambang():
    verdict = sentiment.aggregate(_hasil(*_VETO_MENENTUKAN), CFG)

    assert verdict.score == pytest.approx(0.622)
    assert verdict.label is SentimentLabel.NEGATIF


def test_veto_dapat_dimatikan_lewat_konfigurasi():
    cfg = dataclasses.replace(CFG, veto_on_strong_negative=False)

    verdict = sentiment.aggregate(_hasil(*_VETO_MENENTUKAN), cfg)

    assert verdict.score == pytest.approx(0.622)
    assert verdict.label is SentimentLabel.POSITIF


def test_negatif_lemah_tidak_memveto():
    verdict = sentiment.aggregate(
        _hasil((SentimentLabel.POSITIF, 0.95), (SentimentLabel.NEGATIF, 0.50)), CFG
    )

    assert verdict.label is SentimentLabel.NETRAL
    assert verdict.score == pytest.approx(0.225)


def test_mayoritas_negatif_menghasilkan_verdict_negatif():
    verdict = sentiment.aggregate(
        _hasil((SentimentLabel.NEGATIF, 0.7), (SentimentLabel.NEGATIF, 0.7)), CFG
    )

    assert verdict.label is SentimentLabel.NEGATIF
    assert verdict.score == pytest.approx(-0.7)


def test_daftar_kosong_menghasilkan_netral_tanpa_error():
    verdict = sentiment.aggregate([], CFG)

    assert verdict.label is SentimentLabel.NETRAL
    assert verdict.score == 0.0
    assert verdict.analyzed_count == 0


def test_artikel_kurang_dari_min_articles_menghasilkan_netral():
    cfg = dataclasses.replace(CFG, min_articles=2)

    verdict = sentiment.aggregate(_hasil((SentimentLabel.POSITIF, 0.99)), cfg)

    assert verdict.label is SentimentLabel.NETRAL


def test_verdict_menyimpan_seluruh_hasil_per_artikel():
    hasil = _hasil((SentimentLabel.POSITIF, 0.9), (SentimentLabel.NETRAL, 0.5))

    verdict = sentiment.aggregate(hasil, CFG)

    assert len(verdict.per_article) == 2
    assert verdict.per_article[0].article.url == "u0"
