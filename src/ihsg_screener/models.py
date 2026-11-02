"""Dataclass yang mengalir antar lapisan. Semua immutable."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class Decision(str, Enum):
    BUY_ALERT = "BUY_ALERT"
    REJECTED_TECHNICAL = "REJECTED_TECHNICAL"
    REJECTED_SENTIMENT = "REJECTED_SENTIMENT"
    SKIPPED_NO_NEWS = "SKIPPED_NO_NEWS"
    SKIPPED_DUPLICATE = "SKIPPED_DUPLICATE"
    SKIPPED_NO_DATA = "SKIPPED_NO_DATA"
    ERROR = "ERROR"


class SentimentLabel(str, Enum):
    POSITIF = "POSITIF"
    NETRAL = "NETRAL"
    NEGATIF = "NEGATIF"


@dataclass(frozen=True)
class Ticker:
    symbol: str
    name: str
    aliases: tuple[str, ...] = ()

    @property
    def code(self) -> str:
        """Kode emiten tanpa suffix bursa: 'BBRI.JK' -> 'BBRI'."""
        return self.symbol.split(".")[0]


@dataclass(frozen=True)
class Article:
    title: str
    description: str
    url: str
    source: str
    published_at: str


@dataclass(frozen=True)
class TechnicalSignal:
    symbol: str
    is_bullish: bool
    close: float
    as_of: date
    indicators: dict[str, float] = field(default_factory=dict)
    passed_rules: tuple[str, ...] = ()
    failed_rules: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArticleSentiment:
    article: Article
    label: SentimentLabel
    score: float


@dataclass(frozen=True)
class SentimentVerdict:
    label: SentimentLabel
    score: float
    analyzed_count: int
    rejected_count: int
    per_article: tuple[ArticleSentiment, ...] = ()


@dataclass(frozen=True)
class ScanResult:
    symbol: str
    decision: Decision
    reason: str
    technical: TechnicalSignal | None = None
    sentiment: SentimentVerdict | None = None
