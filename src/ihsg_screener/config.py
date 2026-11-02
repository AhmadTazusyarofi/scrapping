"""Memuat dan memvalidasi konfigurasi dari settings.yaml + variabel lingkungan."""

from __future__ import annotations

import os
from dataclasses import MISSING, dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

from .errors import ConfigError
from .models import Ticker

REQUIRED_SECRETS = ("NEWSAPI_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
REQUIRED_SECTIONS = ("technical", "sentiment", "news", "alerts", "http", "runtime")


@dataclass(frozen=True)
class Secrets:
    newsapi_key: str
    telegram_bot_token: str
    telegram_chat_id: str


SUMBER_BERITA = ("newsapi", "rss")


@dataclass(frozen=True)
class NewsConfig:
    page_size: int
    max_requests_per_run: int
    lookback_days: int
    language: str
    # Kunci di bawah ditambahkan setelah RSS diperkenalkan; semuanya bernilai
    # bawaan agar settings.yaml yang ditulis sebelumnya tetap dapat dimuat.
    source: str = "newsapi"
    feeds: tuple[str, ...] = ()
    max_age_hours: int = 72


@dataclass(frozen=True)
class SentimentConfig:
    model: str
    articles_per_ticker: int
    min_articles: int
    min_avg_score: float
    neutral_weight: float
    veto_on_strong_negative: bool
    strong_negative_threshold: float
    batch_size: int


@dataclass(frozen=True)
class AlertsConfig:
    cooldown_days: int


@dataclass(frozen=True)
class HttpConfig:
    timeout_seconds: int
    retries: int
    backoff_base_seconds: int


@dataclass(frozen=True)
class RuntimeConfig:
    db_path: str
    log_dir: str
    lock_file: str
    max_data_age_days: int


@dataclass(frozen=True)
class Settings:
    technical: dict[str, Any]
    sentiment: SentimentConfig
    news: NewsConfig
    alerts: AlertsConfig
    http: HttpConfig
    runtime: RuntimeConfig
    secrets: Secrets


def _section(data: Mapping[str, Any], name: str) -> dict[str, Any]:
    if name not in data or data[name] is None:
        raise ConfigError(f"settings.yaml: bagian '{name}' hilang")
    return dict(data[name])


def _build(cls, section: Mapping[str, Any], name: str):
    """Bangun dataclass konfigurasi dari satu bagian YAML.

    Hanya field tanpa nilai bawaan yang diwajibkan, sehingga kunci yang
    ditambahkan di versi berikutnya tidak membuat settings.yaml lama gagal.
    """
    fields = cls.__dataclass_fields__
    wajib = {
        n
        for n, f in fields.items()
        if f.default is MISSING and f.default_factory is MISSING
    }
    missing = wajib - set(section)
    if missing:
        raise ConfigError(f"settings.yaml: bagian '{name}' kekurangan kunci {sorted(missing)}")
    return cls(**{k: v for k, v in section.items() if k in fields})


def _load_secrets(env: Mapping[str, str]) -> Secrets:
    missing = [k for k in REQUIRED_SECRETS if not env.get(k)]
    if missing:
        raise ConfigError(f"Variabel lingkungan wajib kosong atau hilang: {', '.join(missing)}")
    return Secrets(
        newsapi_key=env["NEWSAPI_KEY"],
        telegram_bot_token=env["TELEGRAM_BOT_TOKEN"],
        telegram_chat_id=env["TELEGRAM_CHAT_ID"],
    )


def load_settings(config_path: Path, env: Mapping[str, str] | None = None) -> Settings:
    """Muat settings.yaml dan rahasia. Melempar ConfigError bila ada yang kurang."""
    env = os.environ if env is None else env
    path = Path(config_path)
    if not path.is_file():
        raise ConfigError(f"File konfigurasi tidak ditemukan: {path}")

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"settings.yaml tidak dapat diurai: {exc}") from exc

    for name in REQUIRED_SECTIONS:
        _section(data, name)

    technical = _section(data, "technical")
    for key in ("min_bars", "lookback_days", "rules"):
        if key not in technical:
            raise ConfigError(f"settings.yaml: bagian 'technical' kekurangan kunci '{key}'")

    news_section = _section(data, "news")
    if "feeds" in news_section and news_section["feeds"] is not None:
        news_section["feeds"] = tuple(news_section["feeds"])
    news = _build(NewsConfig, news_section, "news")

    if news.source not in SUMBER_BERITA:
        raise ConfigError(
            f"settings.yaml: news.source '{news.source}' tidak dikenal; "
            f"pilihan: {', '.join(SUMBER_BERITA)}"
        )
    if news.source == "rss" and not news.feeds:
        raise ConfigError("settings.yaml: news.source 'rss' memerlukan daftar 'feeds'")

    return Settings(
        technical=technical,
        sentiment=_build(SentimentConfig, _section(data, "sentiment"), "sentiment"),
        news=news,
        alerts=_build(AlertsConfig, _section(data, "alerts"), "alerts"),
        http=_build(HttpConfig, _section(data, "http"), "http"),
        runtime=_build(RuntimeConfig, _section(data, "runtime"), "runtime"),
        secrets=_load_secrets(env),
    )


def load_watchlist(path: Path) -> list[Ticker]:
    """Muat daftar emiten. Melempar ConfigError bila kosong atau tidak valid."""
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"File watchlist tidak ditemukan: {path}")

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"watchlist.yaml tidak dapat diurai: {exc}") from exc

    raw = data.get("tickers") or []
    if not raw:
        raise ConfigError("watchlist.yaml: daftar 'tickers' kosong")

    tickers: list[Ticker] = []
    seen: set[str] = set()
    for entry in raw:
        symbol = (entry or {}).get("symbol")
        name = (entry or {}).get("name")
        if not symbol:
            raise ConfigError("watchlist.yaml: ada entri tanpa 'symbol'")
        if not name:
            raise ConfigError(f"watchlist.yaml: '{symbol}' tidak memiliki 'name'")
        if symbol in seen:
            raise ConfigError(f"watchlist.yaml: simbol duplikat '{symbol}'")
        seen.add(symbol)
        tickers.append(
            Ticker(symbol=symbol, name=name, aliases=tuple(entry.get("aliases") or ()))
        )
    return tickers
