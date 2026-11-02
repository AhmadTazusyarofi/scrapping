"""Pembungkus model IndoBERT: pemuatan malas, verifikasi label, inferensi batch."""

from __future__ import annotations

import logging
from typing import Callable, Mapping, Sequence

from ..errors import LabelMappingError
from ..models import SentimentLabel

logger = logging.getLogger(__name__)

MAX_TOKENS = 512

_ALIASES: dict[str, SentimentLabel] = {
    "positive": SentimentLabel.POSITIF,
    "positif": SentimentLabel.POSITIF,
    "pos": SentimentLabel.POSITIF,
    "negative": SentimentLabel.NEGATIF,
    "negatif": SentimentLabel.NEGATIF,
    "neg": SentimentLabel.NEGATIF,
    "neutral": SentimentLabel.NETRAL,
    "netral": SentimentLabel.NETRAL,
    "neu": SentimentLabel.NETRAL,
}


def map_labels(id2label: Mapping[int | str, str]) -> dict[str, SentimentLabel]:
    """Petakan nama label model ke SentimentLabel.

    Label generik seperti LABEL_0 ditolak, bukan ditebak: menebak arah label
    membalik seluruh gate sentimen tanpa memunculkan satu pun error di log.
    """
    if not id2label:
        raise LabelMappingError("model tidak memiliki id2label atau pemetaannya kosong")

    mapping: dict[str, SentimentLabel] = {}
    tidak_dikenal: list[str] = []
    for name in id2label.values():
        key = str(name).strip().lower()
        if key in _ALIASES:
            mapping[key] = _ALIASES[key]
        else:
            tidak_dikenal.append(str(name))

    if tidak_dikenal:
        raise LabelMappingError(
            f"label model tidak dapat dipetakan: {tidak_dikenal}. "
            "Tetapkan model sentimen dengan label bermakna di settings.yaml, "
            "atau tambahkan aliasnya di sentiment_engine._ALIASES."
        )
    return mapping


def _default_pipeline_factory(model_name: str):
    from transformers import pipeline

    return pipeline("text-classification", model=model_name)


class SentimentEngine:
    """Menjalankan klasifikasi sentimen. Model dimuat pada penggunaan pertama."""

    def __init__(
        self,
        model_name: str,
        batch_size: int = 8,
        pipeline_factory: Callable[[str], object] | None = None,
    ) -> None:
        self.model_name = model_name
        self.batch_size = batch_size
        self._factory = pipeline_factory or _default_pipeline_factory
        self._pipeline = None
        self._labels: dict[str, SentimentLabel] = {}

    @property
    def is_loaded(self) -> bool:
        return self._pipeline is not None

    def _load(self) -> None:
        if self._pipeline is not None:
            return
        logger.info("Memuat model sentimen: %s", self.model_name)
        pipeline = self._factory(self.model_name)
        self._labels = map_labels(pipeline.model.config.id2label)
        self._pipeline = pipeline

    def classify(self, texts: Sequence[str]) -> list[tuple[SentimentLabel, float]]:
        """Klasifikasikan sekumpulan teks sekaligus.

        Pemotongan diserahkan ke tokenizer (truncation=True, max_length=512),
        bukan dilakukan per karakter: batas 512 bersatuan token.
        """
        if not texts:
            return []

        self._load()
        raw = self._pipeline(
            list(texts),
            truncation=True,
            max_length=MAX_TOKENS,
            batch_size=self.batch_size,
        )

        hasil: list[tuple[SentimentLabel, float]] = []
        for item in raw:
            key = str(item["label"]).strip().lower()
            if key not in self._labels:
                raise LabelMappingError(f"label tak terduga dari model: {item['label']}")
            hasil.append((self._labels[key], float(item["score"])))
        return hasil
