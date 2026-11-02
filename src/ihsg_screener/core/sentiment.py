"""Agregasi hasil inferensi per artikel menjadi satu verdict emiten.

Modul murni: menerima label dan skor, tidak pernah memuat model apa pun.
"""

from __future__ import annotations

from typing import Sequence

from ..config import SentimentConfig
from ..models import ArticleSentiment, SentimentLabel, SentimentVerdict


def _contribution(item: ArticleSentiment, neutral_weight: float) -> float:
    if item.label is SentimentLabel.POSITIF:
        return item.score
    if item.label is SentimentLabel.NEGATIF:
        return -item.score
    return neutral_weight * item.score


def aggregate(
    results: Sequence[ArticleSentiment], cfg: SentimentConfig
) -> SentimentVerdict:
    """Gabungkan hasil per artikel menjadi verdict emiten.

    Satu berita negatif berkeyakinan tinggi memveto verdict positif: berita
    buruk yang tegas tidak boleh tertutup oleh beberapa berita positif lemah.
    """
    items = tuple(results)

    if len(items) < cfg.min_articles:
        return SentimentVerdict(
            label=SentimentLabel.NETRAL,
            score=0.0,
            analyzed_count=len(items),
            rejected_count=0,
            per_article=items,
        )

    score = sum(_contribution(i, cfg.neutral_weight) for i in items) / len(items)

    if cfg.veto_on_strong_negative and any(
        i.label is SentimentLabel.NEGATIF and i.score >= cfg.strong_negative_threshold
        for i in items
    ):
        label = SentimentLabel.NEGATIF
    elif score >= cfg.min_avg_score:
        label = SentimentLabel.POSITIF
    elif score <= -cfg.min_avg_score:
        label = SentimentLabel.NEGATIF
    else:
        label = SentimentLabel.NETRAL

    return SentimentVerdict(
        label=label,
        score=round(score, 4),
        analyzed_count=len(items),
        rejected_count=0,
        per_article=items,
    )
