# IHSG Screener — Engine (Project 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Membangun screener EOD saham IDX yang memicu BUY ALERT ke Telegram hanya bila gate teknikal bullish DAN sentimen berita IndoBERT positif, dijalankan terjadwal dan mencatat seluruh hasil ke SQLite.

**Architecture:** Paket berlapis `providers/` (I/O jaringan) — `core/` (logika murni tanpa I/O) — `notifiers/` — `storage/`, dirangkai oleh `pipeline.py` yang menerima seluruh provider sebagai argumen. `cli.py` adalah entry point. Injeksi provider inilah yang membuat seluruh alur dapat diuji end-to-end tanpa jaringan.

**Tech Stack:** Python 3.12, pandas, yfinance, requests, transformers + torch, pyyaml, python-dotenv, tenacity, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-08-25-ihsg-screener-design.md`

## Global Constraints

- Python 3.12 (terpasang di mesin ini: 3.12.6). Direktori kerja: `C:\xampp\htdocs\Scrapping`.
- **Modul di bawah `src/ihsg_screener/core/` TIDAK BOLEH mengimpor `yfinance`, `requests`, `transformers`, `torch`, atau `sqlite3`.** Aturan ini diverifikasi oleh tes di Task 14.
- **Tidak ada tes yang menyentuh jaringan.** Tes yang membutuhkannya ditandai `@pytest.mark.integration` dan dilewati secara default.
- Setiap panggilan HTTP wajib menetapkan `timeout` eksplisit (`http.timeout_seconds: 15`).
- Retry transien: 3 kali, exponential backoff basis 2 detik, via `tenacity`.
- Budget kuota NewsAPI lokal: `news.max_requests_per_run: 40` (di bawah batas 100/hari tier gratis).
- Cooldown dedup alert: `alerts.cooldown_days: 5`.
- Pemotongan teks untuk model: `truncation=True, max_length=512` lewat tokenizer — **tidak boleh** memotong per karakter.
- Exit code: `0` normal, `1` selesai tetapi terdegradasi, `2` fatal.
- Alert dicatat ke tabel `alerts` **hanya setelah** Telegram membalas HTTP 200.
- Semua dataclass di `models.py` bersifat `frozen=True`.
- **Git belum diinisialisasi di direktori ini** (pengguna menanganinya sendiri). Bila `git` belum tersedia saat langkah commit, lewati langkah tersebut dan lanjutkan; jangan menjalankan `git init` sendiri.

---

### Task 1: Scaffolding project & pemuat konfigurasi

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`
- Create: `config/settings.yaml`, `config/watchlist.yaml`
- Create: `src/ihsg_screener/__init__.py`, `src/ihsg_screener/errors.py`, `src/ihsg_screener/config.py`
- Create: `src/ihsg_screener/core/__init__.py`, `src/ihsg_screener/providers/__init__.py`, `src/ihsg_screener/notifiers/__init__.py`, `src/ihsg_screener/storage/__init__.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: —
- Produces:
  - `errors.ConfigError`, `errors.InsufficientDataError`, `errors.StaleDataError`, `errors.QuotaExceededError`, `errors.LabelMappingError`, `errors.NotifierError` (semua turunan `ScreenerError`)
  - `config.Secrets(newsapi_key: str, telegram_bot_token: str, telegram_chat_id: str)`
  - `config.NewsConfig(page_size: int, max_requests_per_run: int, lookback_days: int, language: str)`
  - `config.SentimentConfig(model: str, articles_per_ticker: int, min_articles: int, min_avg_score: float, neutral_weight: float, veto_on_strong_negative: bool, strong_negative_threshold: float, batch_size: int)`
  - `config.AlertsConfig(cooldown_days: int)`
  - `config.HttpConfig(timeout_seconds: int, retries: int, backoff_base_seconds: int)`
  - `config.RuntimeConfig(db_path: str, log_dir: str, lock_file: str, max_data_age_days: int)`
  - `config.Settings(technical: dict, sentiment, news, alerts, http, runtime, secrets)`
  - `config.load_settings(config_path: Path, env: Mapping[str, str]) -> Settings`
  - `config.load_watchlist(path: Path) -> list[Ticker]` — **catatan:** fungsi ini ditambahkan di Task 2 setelah `Ticker` ada. Task 1 tidak membuatnya.

- [ ] **Step 1: Buat struktur direktori dan file paket kosong**

```bash
mkdir -p src/ihsg_screener/core src/ihsg_screener/providers src/ihsg_screener/notifiers src/ihsg_screener/storage config tests data logs
touch src/ihsg_screener/__init__.py src/ihsg_screener/core/__init__.py src/ihsg_screener/providers/__init__.py src/ihsg_screener/notifiers/__init__.py src/ihsg_screener/storage/__init__.py tests/__init__.py
```

- [ ] **Step 2: Tulis `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "ihsg-screener"
version = "0.1.0"
description = "Screener EOD saham IDX: gate teknikal + sentimen berita IndoBERT"
requires-python = ">=3.12"
dependencies = [
    "yfinance>=0.2.40",
    "pandas>=2.2",
    "requests>=2.32",
    "transformers>=4.44",
    "torch>=2.4",
    "pyyaml>=6.0",
    "python-dotenv>=1.0",
    "tenacity>=9.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.3", "pytest-cov>=5.0", "ruff>=0.6"]

[project.scripts]
ihsg-screener = "ihsg_screener.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["integration: butuh jaringan atau model asli; dilewati secara default"]
addopts = "-m 'not integration'"

[tool.ruff]
line-length = 100
target-version = "py312"
```

- [ ] **Step 3: Tulis `.gitignore` dan `.env.example`**

`.gitignore`:

```
__pycache__/
*.py[cod]
.venv/
venv/
*.egg-info/
.pytest_cache/
.ruff_cache/
.env
data/*.db
data/*.lock
logs/
```

`.env.example`:

```
NEWSAPI_KEY=isi_dengan_api_key_newsapi
TELEGRAM_BOT_TOKEN=isi_dengan_token_bot_telegram
TELEGRAM_CHAT_ID=isi_dengan_chat_id_tujuan
```

- [ ] **Step 4: Tulis `config/settings.yaml`**

```yaml
technical:
  min_bars: 60
  lookback_days: 180
  rules:
    sma_cross:
      enabled: true
      fast: 5
      slow: 20
    rsi_not_overbought:
      enabled: false
      period: 14
      max: 70
    macd_bullish:
      enabled: false
      fast: 12
      slow: 26
      signal: 9

sentiment:
  model: wong39/indobert-sentiment-classifier
  articles_per_ticker: 3
  min_articles: 1
  min_avg_score: 0.60
  neutral_weight: 0.0
  veto_on_strong_negative: true
  strong_negative_threshold: 0.80
  batch_size: 8

news:
  page_size: 3
  max_requests_per_run: 40
  lookback_days: 3
  language: id

alerts:
  cooldown_days: 5

http:
  timeout_seconds: 15
  retries: 3
  backoff_base_seconds: 2

runtime:
  db_path: data/scanner.db
  log_dir: logs
  lock_file: data/scanner.lock
  max_data_age_days: 4
```

- [ ] **Step 5: Tulis `config/watchlist.yaml`**

```yaml
tickers:
  - symbol: BBRI.JK
    name: Bank Rakyat Indonesia
    aliases: [BBRI, BRI]
  - symbol: BBCA.JK
    name: Bank Central Asia
    aliases: [BBCA, BCA]
  - symbol: TLKM.JK
    name: Telkom Indonesia
    aliases: [TLKM, Telkom]
  - symbol: ASII.JK
    name: Astra International
    aliases: [ASII, Astra]
  - symbol: ANTM.JK
    name: Aneka Tambang
    aliases: [ANTM, Antam]
```

- [ ] **Step 6: Tulis `src/ihsg_screener/errors.py`**

```python
"""Hierarki exception aplikasi."""


class ScreenerError(Exception):
    """Akar seluruh exception aplikasi."""


class ConfigError(ScreenerError):
    """Konfigurasi hilang atau tidak valid. Fatal: exit 2."""


class InsufficientDataError(ScreenerError):
    """Bar historis tidak cukup untuk menghitung indikator. Per-emiten."""


class StaleDataError(ScreenerError):
    """Bar terbaru terlalu lama; kemungkinan hari libur bursa. Global."""


class QuotaExceededError(ScreenerError):
    """Budget kuota NewsAPI habis. Global terdegradasi."""


class LabelMappingError(ScreenerError):
    """Label model sentimen tidak dapat dipetakan. Fatal: exit 2."""


class NotifierError(ScreenerError):
    """Pengiriman notifikasi gagal. Per-emiten."""
```

- [ ] **Step 7: Tulis tes gagal untuk pemuat konfigurasi**

Buat `tests/test_config.py`:

```python
import pytest
import yaml

from ihsg_screener.config import load_settings
from ihsg_screener.errors import ConfigError

FULL_ENV = {
    "NEWSAPI_KEY": "k",
    "TELEGRAM_BOT_TOKEN": "t",
    "TELEGRAM_CHAT_ID": "c",
}


def _write(tmp_path, data):
    path = tmp_path / "settings.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def _valid_data():
    return {
        "technical": {"min_bars": 60, "lookback_days": 180, "rules": {"sma_cross": {"enabled": True, "fast": 5, "slow": 20}}},
        "sentiment": {"model": "m", "articles_per_ticker": 3, "min_articles": 1,
                      "min_avg_score": 0.6, "neutral_weight": 0.0,
                      "veto_on_strong_negative": True, "strong_negative_threshold": 0.8,
                      "batch_size": 8},
        "news": {"page_size": 3, "max_requests_per_run": 40, "lookback_days": 3, "language": "id"},
        "alerts": {"cooldown_days": 5},
        "http": {"timeout_seconds": 15, "retries": 3, "backoff_base_seconds": 2},
        "runtime": {"db_path": "data/scanner.db", "log_dir": "logs",
                    "lock_file": "data/scanner.lock", "max_data_age_days": 4},
    }


def test_load_settings_membaca_seluruh_bagian(tmp_path):
    settings = load_settings(_write(tmp_path, _valid_data()), FULL_ENV)

    assert settings.news.max_requests_per_run == 40
    assert settings.alerts.cooldown_days == 5
    assert settings.http.timeout_seconds == 15
    assert settings.sentiment.min_avg_score == 0.6
    assert settings.technical["rules"]["sma_cross"]["fast"] == 5
    assert settings.secrets.telegram_chat_id == "c"


def test_load_settings_menolak_rahasia_yang_kosong(tmp_path):
    path = _write(tmp_path, _valid_data())
    env = dict(FULL_ENV, TELEGRAM_BOT_TOKEN="")

    with pytest.raises(ConfigError, match="TELEGRAM_BOT_TOKEN"):
        load_settings(path, env)


def test_load_settings_menolak_bagian_yang_hilang(tmp_path):
    data = _valid_data()
    del data["news"]

    with pytest.raises(ConfigError, match="news"):
        load_settings(_write(tmp_path, data), FULL_ENV)


def test_load_settings_menolak_file_yang_tidak_ada(tmp_path):
    with pytest.raises(ConfigError, match="tidak ditemukan"):
        load_settings(tmp_path / "hilang.yaml", FULL_ENV)
```

- [ ] **Step 8: Jalankan tes, pastikan GAGAL**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ihsg_screener.config'`

- [ ] **Step 9: Tulis `src/ihsg_screener/config.py`**

```python
"""Memuat dan memvalidasi konfigurasi dari settings.yaml + variabel lingkungan."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from .errors import ConfigError

REQUIRED_SECRETS = ("NEWSAPI_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
REQUIRED_SECTIONS = ("technical", "sentiment", "news", "alerts", "http", "runtime")


@dataclass(frozen=True)
class Secrets:
    newsapi_key: str
    telegram_bot_token: str
    telegram_chat_id: str


@dataclass(frozen=True)
class NewsConfig:
    page_size: int
    max_requests_per_run: int
    lookback_days: int
    language: str


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
    fields = {f for f in cls.__dataclass_fields__}
    missing = fields - set(section)
    if missing:
        raise ConfigError(f"settings.yaml: bagian '{name}' kekurangan kunci {sorted(missing)}")
    return cls(**{k: section[k] for k in fields})


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

    return Settings(
        technical=technical,
        sentiment=_build(SentimentConfig, _section(data, "sentiment"), "sentiment"),
        news=_build(NewsConfig, _section(data, "news"), "news"),
        alerts=_build(AlertsConfig, _section(data, "alerts"), "alerts"),
        http=_build(HttpConfig, _section(data, "http"), "http"),
        runtime=_build(RuntimeConfig, _section(data, "runtime"), "runtime"),
        secrets=_load_secrets(env),
    )
```

- [ ] **Step 10: Pasang paket dalam mode editable dan jalankan tes**

Run:
```bash
python -m pip install -e ".[dev]"
python -m pytest tests/test_config.py -v
```
Expected: 4 tes PASS

- [ ] **Step 11: Commit**

```bash
git add pyproject.toml .gitignore .env.example config/ src/ tests/
git commit -m "feat: scaffolding project dan pemuat konfigurasi tervalidasi"
```

---

### Task 2: Data model & pemuat watchlist

**Files:**
- Create: `src/ihsg_screener/models.py`
- Modify: `src/ihsg_screener/config.py` (tambah `load_watchlist`)
- Test: `tests/test_models.py`, `tests/test_watchlist.py`

**Interfaces:**
- Consumes: `errors.ConfigError` (Task 1)
- Produces:
  - `models.Decision` — enum: `BUY_ALERT`, `REJECTED_TECHNICAL`, `REJECTED_SENTIMENT`, `SKIPPED_NO_NEWS`, `SKIPPED_DUPLICATE`, `SKIPPED_NO_DATA`, `ERROR`
  - `models.SentimentLabel` — enum: `POSITIF`, `NETRAL`, `NEGATIF`
  - `models.Ticker(symbol, name, aliases: tuple[str, ...])`
  - `models.Article(title, description, url, source, published_at)`
  - `models.TechnicalSignal(symbol, is_bullish, close, as_of: date, indicators: dict[str, float], passed_rules: tuple[str, ...], failed_rules: tuple[str, ...])`
  - `models.ArticleSentiment(article, label, score)`
  - `models.SentimentVerdict(label, score, analyzed_count, rejected_count, per_article: tuple[ArticleSentiment, ...])`
  - `models.ScanResult(symbol, decision, reason, technical=None, sentiment=None)`
  - `config.load_watchlist(path: Path) -> list[Ticker]`

- [ ] **Step 1: Tulis tes gagal untuk model**

Buat `tests/test_models.py`:

```python
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
```

- [ ] **Step 2: Jalankan tes, pastikan GAGAL**

Run: `python -m pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ihsg_screener.models'`

- [ ] **Step 3: Tulis `src/ihsg_screener/models.py`**

```python
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
```

- [ ] **Step 4: Jalankan tes, pastikan LULUS**

Run: `python -m pytest tests/test_models.py -v`
Expected: semua PASS

- [ ] **Step 5: Tulis tes gagal untuk `load_watchlist`**

Buat `tests/test_watchlist.py`:

```python
import pytest
import yaml

from ihsg_screener.config import load_watchlist
from ihsg_screener.errors import ConfigError


def _write(tmp_path, data):
    path = tmp_path / "watchlist.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_load_watchlist_mengurai_ticker(tmp_path):
    path = _write(tmp_path, {"tickers": [
        {"symbol": "BBRI.JK", "name": "Bank Rakyat Indonesia", "aliases": ["BBRI", "BRI"]},
        {"symbol": "TLKM.JK", "name": "Telkom Indonesia"},
    ]})

    tickers = load_watchlist(path)

    assert [t.symbol for t in tickers] == ["BBRI.JK", "TLKM.JK"]
    assert tickers[0].aliases == ("BBRI", "BRI")
    assert tickers[1].aliases == ()
    assert tickers[0].code == "BBRI"


def test_load_watchlist_menolak_daftar_kosong(tmp_path):
    with pytest.raises(ConfigError, match="kosong"):
        load_watchlist(_write(tmp_path, {"tickers": []}))


def test_load_watchlist_menolak_ticker_tanpa_nama(tmp_path):
    path = _write(tmp_path, {"tickers": [{"symbol": "BBRI.JK"}]})

    with pytest.raises(ConfigError, match="name"):
        load_watchlist(path)


def test_load_watchlist_menolak_simbol_duplikat(tmp_path):
    path = _write(tmp_path, {"tickers": [
        {"symbol": "BBRI.JK", "name": "A"},
        {"symbol": "BBRI.JK", "name": "B"},
    ]})

    with pytest.raises(ConfigError, match="duplikat"):
        load_watchlist(path)
```

- [ ] **Step 6: Jalankan tes, pastikan GAGAL**

Run: `python -m pytest tests/test_watchlist.py -v`
Expected: FAIL — `ImportError: cannot import name 'load_watchlist'`

- [ ] **Step 7: Tambahkan `load_watchlist` ke `config.py`**

Tambahkan import di bagian atas `config.py`:

```python
from .models import Ticker
```

Tambahkan fungsi di akhir `config.py`:

```python
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
```

- [ ] **Step 8: Jalankan seluruh tes**

Run: `python -m pytest tests/ -v`
Expected: semua PASS

- [ ] **Step 9: Commit**

```bash
git add src/ihsg_screener/models.py src/ihsg_screener/config.py tests/test_models.py tests/test_watchlist.py
git commit -m "feat: data model immutable dan pemuat watchlist"
```

---

### Task 3: Indikator teknikal (pandas murni)

**Files:**
- Create: `src/ihsg_screener/core/indicators.py`
- Test: `tests/core/test_indicators.py`

**Interfaces:**
- Consumes: —
- Produces:
  - `indicators.sma(series: pd.Series, period: int) -> pd.Series`
  - `indicators.rsi(series: pd.Series, period: int = 14) -> pd.Series`
  - `indicators.macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame` — kolom `macd`, `signal`, `hist`
  - `indicators.bollinger(series: pd.Series, period: int = 20, num_std: float = 2.0) -> pd.DataFrame` — kolom `upper`, `mid`, `lower`

**Catatan:** modul ini tidak boleh mengimpor apa pun selain `pandas`.

- [ ] **Step 1: Tulis tes gagal**

Buat `tests/core/__init__.py` (kosong) dan `tests/core/test_indicators.py`:

```python
import pandas as pd
import pytest

from ihsg_screener.core import indicators


def test_sma_menghitung_rata_rata_bergerak():
    series = pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], dtype=float)

    result = indicators.sma(series, 3)

    assert pd.isna(result.iloc[0])
    assert pd.isna(result.iloc[1])
    assert result.iloc[2] == pytest.approx(2.0)
    assert result.iloc[-1] == pytest.approx(9.0)


def test_sma_mengembalikan_nan_bila_bar_kurang_dari_periode():
    series = pd.Series([1, 2], dtype=float)

    assert indicators.sma(series, 5).isna().all()


def test_rsi_seratus_untuk_deret_naik_monoton():
    series = pd.Series(range(1, 41), dtype=float)

    assert indicators.rsi(series, 14).iloc[-1] == pytest.approx(100.0)


def test_rsi_nol_untuk_deret_turun_monoton():
    series = pd.Series(range(40, 0, -1), dtype=float)

    assert indicators.rsi(series, 14).iloc[-1] == pytest.approx(0.0)


def test_rsi_lima_puluh_untuk_deret_datar():
    series = pd.Series([100.0] * 40)

    assert indicators.rsi(series, 14).iloc[-1] == pytest.approx(50.0)


def test_macd_nol_untuk_deret_datar():
    series = pd.Series([100.0] * 60)

    result = indicators.macd(series)

    assert list(result.columns) == ["macd", "signal", "hist"]
    assert result["macd"].iloc[-1] == pytest.approx(0.0)
    assert result["hist"].iloc[-1] == pytest.approx(0.0)


def test_macd_positif_untuk_deret_naik():
    series = pd.Series(range(1, 101), dtype=float)

    assert indicators.macd(series)["macd"].iloc[-1] > 0


def test_bollinger_pita_menyempit_pada_deret_datar():
    series = pd.Series([100.0] * 40)

    result = indicators.bollinger(series, period=20, num_std=2.0)

    assert list(result.columns) == ["upper", "mid", "lower"]
    assert result["mid"].iloc[-1] == pytest.approx(100.0)
    assert result["upper"].iloc[-1] == pytest.approx(100.0)
    assert result["lower"].iloc[-1] == pytest.approx(100.0)


def test_bollinger_upper_di_atas_lower_pada_deret_berfluktuasi():
    series = pd.Series([100, 105, 95, 110, 90] * 8, dtype=float)

    result = indicators.bollinger(series, period=20, num_std=2.0)

    assert result["upper"].iloc[-1] > result["mid"].iloc[-1] > result["lower"].iloc[-1]
```

- [ ] **Step 2: Jalankan tes, pastikan GAGAL**

Run: `python -m pytest tests/core/test_indicators.py -v`
Expected: FAIL — `ImportError: cannot import name 'indicators'`

- [ ] **Step 3: Tulis `src/ihsg_screener/core/indicators.py`**

```python
"""Indikator teknikal dengan pandas murni. Tanpa I/O, tanpa dependensi eksternal."""

from __future__ import annotations

import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average. NaN sampai jumlah bar mencukupi periode."""
    return series.rolling(window=period, min_periods=period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index dengan pemulusan Wilder.

    Konvensi tepi: tanpa kerugian sama sekali -> 100; tanpa keuntungan sama
    sekali -> 0; deret datar (keduanya nol) -> 50.
    """
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()

    rs = avg_gain / avg_loss
    result = 100.0 - (100.0 / (1.0 + rs))

    flat = (avg_gain == 0) & (avg_loss == 0)
    only_gain = (avg_loss == 0) & (avg_gain > 0)
    only_loss = (avg_gain == 0) & (avg_loss > 0)

    result = result.mask(flat, 50.0)
    result = result.mask(only_gain, 100.0)
    result = result.mask(only_loss, 0.0)
    return result


def macd(
    series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    """MACD, garis sinyal, dan histogram."""
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return pd.DataFrame(
        {"macd": macd_line, "signal": signal_line, "hist": macd_line - signal_line}
    )


def bollinger(
    series: pd.Series, period: int = 20, num_std: float = 2.0
) -> pd.DataFrame:
    """Bollinger Bands di sekitar SMA."""
    mid = sma(series, period)
    std = series.rolling(window=period, min_periods=period).std(ddof=0)
    return pd.DataFrame(
        {"upper": mid + num_std * std, "mid": mid, "lower": mid - num_std * std}
    )
```

- [ ] **Step 4: Jalankan tes, pastikan LULUS**

Run: `python -m pytest tests/core/test_indicators.py -v`
Expected: 9 tes PASS

- [ ] **Step 5: Commit**

```bash
git add src/ihsg_screener/core/indicators.py tests/core/
git commit -m "feat: indikator SMA, RSI, MACD, Bollinger dengan pandas murni"
```

---

### Task 4: Registry aturan & evaluasi strategi

**Files:**
- Create: `src/ihsg_screener/core/strategy.py`
- Test: `tests/core/test_strategy.py`

**Interfaces:**
- Consumes: `indicators.sma/rsi/macd` (Task 3), `models.TechnicalSignal` (Task 2), `errors.InsufficientDataError` (Task 1)
- Produces:
  - `strategy.RULES: dict[str, RuleFn]` dengan `RuleFn = Callable[[pd.DataFrame, dict], tuple[bool, dict[str, float]]]`
  - `strategy.register(name: str)` — dekorator pendaftaran aturan
  - `strategy.evaluate(symbol: str, df: pd.DataFrame, technical_config: dict) -> TechnicalSignal`
  - Aturan bawaan: `sma_cross`, `rsi_not_overbought`, `macd_bullish`

**Kontrak `evaluate`:** DataFrame wajib memiliki kolom `Close` dan index bertipe tanggal. Emiten bullish bila **seluruh** aturan yang `enabled: true` lulus. Bila `len(df) < min_bars`, lempar `InsufficientDataError`.

- [ ] **Step 1: Tulis tes gagal**

Buat `tests/core/test_strategy.py`:

```python
import pandas as pd
import pytest

from ihsg_screener.core import strategy
from ihsg_screener.errors import InsufficientDataError


def _frame(values):
    idx = pd.date_range("2026-01-01", periods=len(values), freq="B")
    return pd.DataFrame({"Close": [float(v) for v in values]}, index=idx)


def _config(rules, min_bars=10):
    return {"min_bars": min_bars, "lookback_days": 180, "rules": rules}


NAIK = list(range(1, 61))
TURUN = list(range(60, 0, -1))


def test_sma_cross_lulus_pada_tren_naik():
    config = _config({"sma_cross": {"enabled": True, "fast": 5, "slow": 20}})

    signal = strategy.evaluate("BBRI.JK", _frame(NAIK), config)

    assert signal.is_bullish is True
    assert signal.passed_rules == ("sma_cross",)
    assert signal.failed_rules == ()
    assert signal.indicators["sma_fast"] > signal.indicators["sma_slow"]


def test_sma_cross_gagal_pada_tren_turun():
    config = _config({"sma_cross": {"enabled": True, "fast": 5, "slow": 20}})

    signal = strategy.evaluate("BBRI.JK", _frame(TURUN), config)

    assert signal.is_bullish is False
    assert signal.failed_rules == ("sma_cross",)


def test_aturan_yang_dinonaktifkan_tidak_dievaluasi():
    config = _config({
        "sma_cross": {"enabled": True, "fast": 5, "slow": 20},
        "rsi_not_overbought": {"enabled": False, "period": 14, "max": 70},
    })

    signal = strategy.evaluate("BBRI.JK", _frame(NAIK), config)

    assert signal.passed_rules == ("sma_cross",)
    assert "rsi" not in signal.indicators


def test_bullish_hanya_bila_semua_aturan_aktif_lulus():
    # Tren naik monoton: sma_cross lulus, tetapi RSI = 100 sehingga overbought.
    config = _config({
        "sma_cross": {"enabled": True, "fast": 5, "slow": 20},
        "rsi_not_overbought": {"enabled": True, "period": 14, "max": 70},
    })

    signal = strategy.evaluate("BBRI.JK", _frame(NAIK), config)

    assert signal.is_bullish is False
    assert signal.passed_rules == ("sma_cross",)
    assert signal.failed_rules == ("rsi_not_overbought",)


def test_macd_bullish_lulus_pada_tren_naik():
    config = _config({"macd_bullish": {"enabled": True, "fast": 12, "slow": 26, "signal": 9}})

    signal = strategy.evaluate("BBRI.JK", _frame(NAIK), config)

    assert signal.is_bullish is True
    assert signal.indicators["macd"] > signal.indicators["macd_signal"]


def test_evaluate_menolak_bar_yang_kurang():
    config = _config({"sma_cross": {"enabled": True, "fast": 5, "slow": 20}}, min_bars=60)

    with pytest.raises(InsufficientDataError, match="bar"):
        strategy.evaluate("BBRI.JK", _frame(NAIK[:30]), config)


def test_evaluate_menolak_aturan_yang_tidak_dikenal():
    config = _config({"aturan_hantu": {"enabled": True}})

    with pytest.raises(KeyError, match="aturan_hantu"):
        strategy.evaluate("BBRI.JK", _frame(NAIK), config)


def test_evaluate_mengisi_close_dan_tanggal():
    config = _config({"sma_cross": {"enabled": True, "fast": 5, "slow": 20}})
    df = _frame(NAIK)

    signal = strategy.evaluate("BBRI.JK", df, config)

    assert signal.symbol == "BBRI.JK"
    assert signal.close == pytest.approx(60.0)
    assert signal.as_of == df.index[-1].date()


def test_tanpa_aturan_aktif_tidak_dianggap_bullish():
    config = _config({"sma_cross": {"enabled": False, "fast": 5, "slow": 20}})

    signal = strategy.evaluate("BBRI.JK", _frame(NAIK), config)

    assert signal.is_bullish is False
    assert signal.passed_rules == ()
```

- [ ] **Step 2: Jalankan tes, pastikan GAGAL**

Run: `python -m pytest tests/core/test_strategy.py -v`
Expected: FAIL — `ImportError: cannot import name 'strategy'`

- [ ] **Step 3: Tulis `src/ihsg_screener/core/strategy.py`**

```python
"""Registry aturan teknikal dan evaluasinya menjadi TechnicalSignal."""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from ..errors import InsufficientDataError
from ..models import TechnicalSignal
from . import indicators

RuleFn = Callable[[pd.DataFrame, dict[str, Any]], tuple[bool, dict[str, float]]]

RULES: dict[str, RuleFn] = {}


def register(name: str) -> Callable[[RuleFn], RuleFn]:
    """Daftarkan sebuah aturan ke registry global."""

    def decorator(fn: RuleFn) -> RuleFn:
        RULES[name] = fn
        return fn

    return decorator


@register("sma_cross")
def _sma_cross(df: pd.DataFrame, params: dict[str, Any]) -> tuple[bool, dict[str, float]]:
    fast = indicators.sma(df["Close"], params["fast"]).iloc[-1]
    slow = indicators.sma(df["Close"], params["slow"]).iloc[-1]
    values = {"sma_fast": float(fast), "sma_slow": float(slow)}
    if pd.isna(fast) or pd.isna(slow):
        return False, values
    return bool(fast > slow), values


@register("rsi_not_overbought")
def _rsi_not_overbought(
    df: pd.DataFrame, params: dict[str, Any]
) -> tuple[bool, dict[str, float]]:
    value = indicators.rsi(df["Close"], params["period"]).iloc[-1]
    values = {"rsi": float(value)}
    if pd.isna(value):
        return False, values
    return bool(value < params["max"]), values


@register("macd_bullish")
def _macd_bullish(df: pd.DataFrame, params: dict[str, Any]) -> tuple[bool, dict[str, float]]:
    frame = indicators.macd(
        df["Close"], params["fast"], params["slow"], params["signal"]
    )
    macd_value = frame["macd"].iloc[-1]
    signal_value = frame["signal"].iloc[-1]
    values = {"macd": float(macd_value), "macd_signal": float(signal_value)}
    if pd.isna(macd_value) or pd.isna(signal_value):
        return False, values
    return bool(macd_value > signal_value), values


def evaluate(
    symbol: str, df: pd.DataFrame, technical_config: dict[str, Any]
) -> TechnicalSignal:
    """Evaluasi seluruh aturan yang aktif. Bullish bila semuanya lulus.

    Melempar InsufficientDataError bila bar kurang dari min_bars, dan KeyError
    bila konfigurasi menyebut aturan yang tidak terdaftar.
    """
    min_bars = technical_config["min_bars"]
    if len(df) < min_bars:
        raise InsufficientDataError(
            f"{symbol}: hanya {len(df)} bar, minimal {min_bars} bar dibutuhkan"
        )

    passed: list[str] = []
    failed: list[str] = []
    values: dict[str, float] = {}

    for name, params in technical_config["rules"].items():
        if not params.get("enabled", False):
            continue
        if name not in RULES:
            raise KeyError(f"Aturan tidak dikenal dalam settings.yaml: '{name}'")
        ok, rule_values = RULES[name](df, params)
        values.update(rule_values)
        (passed if ok else failed).append(name)

    return TechnicalSignal(
        symbol=symbol,
        is_bullish=bool(passed) and not failed,
        close=float(df["Close"].iloc[-1]),
        as_of=df.index[-1].date(),
        indicators=values,
        passed_rules=tuple(passed),
        failed_rules=tuple(failed),
    )
```

- [ ] **Step 4: Jalankan tes, pastikan LULUS**

Run: `python -m pytest tests/core/test_strategy.py -v`
Expected: 9 tes PASS

- [ ] **Step 5: Commit**

```bash
git add src/ihsg_screener/core/strategy.py tests/core/test_strategy.py
git commit -m "feat: registry aturan teknikal dengan gate AND yang dapat dikonfigurasi"
```

---

### Task 5: Pembersihan teks & filter relevansi

**Files:**
- Create: `src/ihsg_screener/core/textproc.py`
- Test: `tests/core/test_textproc.py`

**Interfaces:**
- Consumes: `models.Article`, `models.Ticker` (Task 2)
- Produces:
  - `textproc.clean_text(text: str, source: str = "") -> str`
  - `textproc.is_relevant(article: Article, ticker: Ticker) -> bool`
  - `textproc.prepare(article: Article) -> str` — mengembalikan `"{judul}. {deskripsi}"`
  - `textproc.prepare_articles(articles: Sequence[Article], ticker: Ticker) -> list[tuple[Article, str]]`

**Catatan desain:** suffix sumber dipangkas menggunakan `article.source` milik artikel itu sendiri, bukan pola generik `" - <apa saja>"`, agar judul yang memang mengandung tanda hubung tidak ikut terpotong. Pemotongan 512 token **tidak** dilakukan di sini — itu tugas tokenizer di Task 10.

- [ ] **Step 1: Tulis tes gagal**

Buat `tests/core/test_textproc.py`:

```python
import pytest

from ihsg_screener.core import textproc
from ihsg_screener.models import Article, Ticker

BBRI = Ticker(symbol="BBRI.JK", name="Bank Rakyat Indonesia", aliases=("BBRI", "BRI"))


def _article(title="", description="", source="Detikcom"):
    return Article(
        title=title,
        description=description,
        url="https://contoh.id/a",
        source=source,
        published_at="2026-08-25T10:00:00Z",
    )


def test_clean_text_membuang_tag_html_dan_entitas():
    assert textproc.clean_text("<b>Laba</b> naik &amp; kuat") == "Laba naik & kuat"


def test_clean_text_membuang_url():
    hasil = textproc.clean_text("Baca di https://contoh.id/berita/123 sekarang")

    assert "https" not in hasil
    assert hasil == "Baca di sekarang"


def test_clean_text_membuang_penanda_potongan_newsapi():
    assert textproc.clean_text("Laba naik tajam… [+1423 chars]") == "Laba naik tajam"


def test_clean_text_membuang_suffix_sumber():
    hasil = textproc.clean_text("BBRI cetak laba - Detikcom", source="Detikcom")

    assert hasil == "BBRI cetak laba"


def test_clean_text_mempertahankan_tanda_hubung_yang_bukan_suffix_sumber():
    hasil = textproc.clean_text("Laba naik 10 - 15 persen", source="Detikcom")

    assert hasil == "Laba naik 10 - 15 persen"


def test_clean_text_merapatkan_spasi_berlebih():
    assert textproc.clean_text("Laba    naik\n\ntajam") == "Laba naik tajam"


def test_is_relevant_menerima_kecocokan_nama_perusahaan():
    artikel = _article(title="Bank Rakyat Indonesia cetak laba", description="")

    assert textproc.is_relevant(artikel, BBRI) is True


def test_is_relevant_menerima_kecocokan_alias():
    artikel = _article(title="Saham BBRI menguat", description="")

    assert textproc.is_relevant(artikel, BBRI) is True


def test_is_relevant_tidak_peduli_besar_kecil_huruf():
    artikel = _article(title="saham bri menguat", description="")

    assert textproc.is_relevant(artikel, BBRI) is True


def test_is_relevant_menolak_artikel_yang_tidak_menyebut_emiten():
    artikel = _article(title="IHSG ditutup menguat", description="Indeks naik 1 persen")

    assert textproc.is_relevant(artikel, BBRI) is False


def test_is_relevant_menolak_alias_yang_hanya_bagian_kata():
    artikel = _article(title="Negara BRICS bertemu", description="")

    assert textproc.is_relevant(artikel, BBRI) is False


def test_prepare_menempatkan_judul_di_depan():
    artikel = _article(title="BBRI cetak laba", description="Laba naik 12 persen")

    assert textproc.prepare(artikel) == "BBRI cetak laba. Laba naik 12 persen"


def test_prepare_menangani_deskripsi_kosong():
    assert textproc.prepare(_article(title="BBRI cetak laba")) == "BBRI cetak laba"


def test_prepare_articles_membuang_artikel_removed():
    artikel = [
        _article(title="[Removed]", description="[Removed]"),
        _article(title="BBRI cetak laba", description="Naik 12 persen"),
    ]

    hasil = textproc.prepare_articles(artikel, BBRI)

    assert len(hasil) == 1
    assert hasil[0][1] == "BBRI cetak laba. Naik 12 persen"


def test_prepare_articles_membuang_artikel_tidak_relevan():
    artikel = [
        _article(title="IHSG ditutup menguat", description="Indeks naik"),
        _article(title="BBRI cetak laba", description="Naik 12 persen"),
    ]

    hasil = textproc.prepare_articles(artikel, BBRI)

    assert [a.title for a, _ in hasil] == ["BBRI cetak laba"]


def test_prepare_articles_membuang_teks_yang_kosong_setelah_dibersihkan():
    # Relevan (mengandung 'BBRI'), tetapi tidak menyisakan teks setelah URL dibuang.
    artikel = [_article(title="https://contoh.id/BBRI", description="")]

    assert textproc.is_relevant(artikel[0], BBRI) is True
    assert textproc.prepare_articles(artikel, BBRI) == []
```

- [ ] **Step 2: Jalankan tes, pastikan GAGAL**

Run: `python -m pytest tests/core/test_textproc.py -v`
Expected: FAIL — `ImportError: cannot import name 'textproc'`

- [ ] **Step 3: Tulis `src/ihsg_screener/core/textproc.py`**

```python
"""Pembersihan teks berita dan filter relevansi sebelum inferensi.

Pemotongan 512 token dikerjakan tokenizer di providers/sentiment_engine.py,
bukan di sini. Modul ini murni: tanpa I/O dan tanpa dependensi eksternal.
"""

from __future__ import annotations

import html
import re
from typing import Sequence

from ..models import Article, Ticker

_TAG = re.compile(r"<[^>]+>")
_URL = re.compile(r"https?://\S+|www\.\S+")
_TRUNCATION = re.compile(r"[…\.]*\s*\[\+\s*\d+\s*chars?\]", re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")
_REMOVED = "[removed]"


def clean_text(text: str, source: str = "") -> str:
    """Bersihkan satu potong teks berita.

    Suffix sumber dipangkas hanya bila cocok persis dengan nama sumber artikel,
    sehingga judul yang memuat tanda hubung biasa tidak ikut terpotong.
    """
    if not text:
        return ""

    result = html.unescape(text)
    result = _TAG.sub(" ", result)
    result = _TRUNCATION.sub(" ", result)
    result = _URL.sub(" ", result)

    if source:
        suffix = re.compile(
            r"\s*[-|–—]\s*" + re.escape(source) + r"\s*$", re.IGNORECASE
        )
        result = suffix.sub("", result)

    return _WHITESPACE.sub(" ", result).strip()


def is_relevant(article: Article, ticker: Ticker) -> bool:
    """True bila nama emiten atau aliasnya muncul sebagai kata utuh."""
    haystack = f"{article.title} {article.description}".lower()
    needles = [ticker.name, ticker.code, *ticker.aliases]
    return any(
        re.search(r"\b" + re.escape(n.lower()) + r"\b", haystack)
        for n in needles
        if n
    )


def prepare(article: Article) -> str:
    """Gabungkan judul dan deskripsi yang sudah bersih, judul di depan."""
    title = clean_text(article.title, article.source)
    description = clean_text(article.description, article.source)
    if title and description:
        return f"{title}. {description}"
    return title or description


def prepare_articles(
    articles: Sequence[Article], ticker: Ticker
) -> list[tuple[Article, str]]:
    """Saring dan siapkan artikel untuk inferensi.

    Membuang artikel '[Removed]', artikel yang tidak menyebut emiten, dan
    artikel yang tidak menyisakan teks apa pun setelah dibersihkan.
    """
    prepared: list[tuple[Article, str]] = []
    for article in articles:
        if article.title.strip().lower() == _REMOVED:
            continue
        if not is_relevant(article, ticker):
            continue
        text = prepare(article)
        if not text:
            continue
        prepared.append((article, text))
    return prepared
```

- [ ] **Step 4: Jalankan tes, pastikan LULUS**

Run: `python -m pytest tests/core/test_textproc.py -v`
Expected: 16 tes PASS

- [ ] **Step 5: Commit**

```bash
git add src/ihsg_screener/core/textproc.py tests/core/test_textproc.py
git commit -m "feat: pembersihan teks berita dan filter relevansi emiten"
```

---

### Task 6: Agregasi sentimen

**Files:**
- Create: `src/ihsg_screener/core/sentiment.py`
- Test: `tests/core/test_sentiment.py`

**Interfaces:**
- Consumes: `models.ArticleSentiment`, `models.SentimentVerdict`, `models.SentimentLabel` (Task 2), `config.SentimentConfig` (Task 1)
- Produces:
  - `sentiment.aggregate(results: Sequence[ArticleSentiment], cfg: SentimentConfig) -> SentimentVerdict`

**Aturan agregasi:**
1. Bila `len(results) < cfg.min_articles` → `NETRAL`, skor `0.0`.
2. Bila `cfg.veto_on_strong_negative` dan ada artikel `NEGATIF` dengan `score >= cfg.strong_negative_threshold` → `NEGATIF` (veto langsung).
3. Skor gabungan = rata-rata kontribusi bertanda: `POSITIF` menyumbang `+score`, `NEGATIF` menyumbang `-score`, `NETRAL` menyumbang `cfg.neutral_weight * score`.
4. `POSITIF` bila skor `>= cfg.min_avg_score`; `NEGATIF` bila skor `<= -cfg.min_avg_score`; selain itu `NETRAL`.

- [ ] **Step 1: Tulis tes gagal**

Buat `tests/core/test_sentiment.py`:

```python
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
# (Angka yang lebih kecil membuat rata-rata sendiri jatuh di bawah ambang,
# sehingga tesnya lulus tanpa pernah menyentuh jalur veto.)
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
    cfg = dataclasses_replace(CFG, veto_on_strong_negative=False)

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
    cfg = dataclasses_replace(CFG, min_articles=2)

    verdict = sentiment.aggregate(_hasil((SentimentLabel.POSITIF, 0.99)), cfg)

    assert verdict.label is SentimentLabel.NETRAL


def test_verdict_menyimpan_seluruh_hasil_per_artikel():
    hasil = _hasil((SentimentLabel.POSITIF, 0.9), (SentimentLabel.NETRAL, 0.5))

    verdict = sentiment.aggregate(hasil, CFG)

    assert len(verdict.per_article) == 2
    assert verdict.per_article[0].article.url == "u0"


def dataclasses_replace(cfg, **kwargs):
    import dataclasses

    return dataclasses.replace(cfg, **kwargs)
```

- [ ] **Step 2: Jalankan tes, pastikan GAGAL**

Run: `python -m pytest tests/core/test_sentiment.py -v`
Expected: FAIL — `ImportError: cannot import name 'sentiment'`

- [ ] **Step 3: Tulis `src/ihsg_screener/core/sentiment.py`**

```python
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
```

- [ ] **Step 4: Jalankan tes, pastikan LULUS**

Run: `python -m pytest tests/core/test_sentiment.py -v`
Expected: 11 tes PASS

- [ ] **Step 5: Commit**

```bash
git add src/ihsg_screener/core/sentiment.py tests/core/test_sentiment.py
git commit -m "feat: agregasi sentimen dengan veto berita negatif kuat"
```

---

### Task 7: Penyimpanan SQLite

**Files:**
- Create: `src/ihsg_screener/storage/schema.sql`
- Create: `src/ihsg_screener/storage/repository.py`
- Test: `tests/storage/test_repository.py`

**Interfaces:**
- Consumes: `models.ScanResult`, `models.Decision`, `models.TechnicalSignal`, `models.SentimentVerdict` (Task 2)
- Produces:
  - `repository.Repository(db_path: str | Path)` — membuat direktori induk dan menerapkan skema saat inisialisasi
  - `.start_run(started_at: datetime | None = None) -> int`
  - `.finish_run(run_id: int, status: str, scanned: int, candidates: int, alerts: int, notes: str = "") -> None`
  - `.record_result(run_id: int, result: ScanResult, as_of: date | None = None) -> None`
  - `.record_alert(run_id: int, symbol: str, as_of: date, close: float, payload: dict, sent_at: datetime | None = None) -> None`
  - `.recently_alerted(symbol: str, cooldown_days: int, now: datetime | None = None) -> bool`
  - `.close() -> None`

- [ ] **Step 1: Tulis `src/ihsg_screener/storage/schema.sql`**

```sql
CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    status       TEXT NOT NULL,
    scanned      INTEGER DEFAULT 0,
    candidates   INTEGER DEFAULT 0,
    alerts       INTEGER DEFAULT 0,
    notes        TEXT
);

CREATE TABLE IF NOT EXISTS scan_results (
    id              INTEGER PRIMARY KEY,
    run_id          INTEGER NOT NULL REFERENCES runs(id),
    symbol          TEXT NOT NULL,
    as_of           TEXT,
    decision        TEXT NOT NULL,
    reason          TEXT,
    close           REAL,
    indicators      TEXT,
    sentiment_label TEXT,
    sentiment_score REAL,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY,
    run_id      INTEGER NOT NULL REFERENCES runs(id),
    symbol      TEXT NOT NULL,
    as_of       TEXT NOT NULL,
    close       REAL NOT NULL,
    payload     TEXT NOT NULL,
    sent_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_alerts_symbol_sent ON alerts(symbol, sent_at);
CREATE INDEX IF NOT EXISTS idx_scan_run ON scan_results(run_id);
```

- [ ] **Step 2: Tulis tes gagal**

Buat `tests/storage/__init__.py` (kosong) dan `tests/storage/test_repository.py`:

```python
import json
from datetime import date, datetime, timedelta

import pytest

from ihsg_screener.models import Decision, ScanResult, SentimentLabel, SentimentVerdict, TechnicalSignal
from ihsg_screener.storage.repository import Repository


@pytest.fixture()
def repo(tmp_path):
    r = Repository(tmp_path / "sub" / "scanner.db")
    yield r
    r.close()


def _signal(symbol="BBRI.JK"):
    return TechnicalSignal(
        symbol=symbol,
        is_bullish=True,
        close=5000.0,
        as_of=date(2026, 8, 25),
        indicators={"sma_fast": 5010.0, "sma_slow": 4900.0},
        passed_rules=("sma_cross",),
        failed_rules=(),
    )


def _verdict():
    return SentimentVerdict(
        label=SentimentLabel.POSITIF, score=0.85, analyzed_count=2, rejected_count=1
    )


def test_membuat_direktori_induk_dan_tabel(tmp_path):
    repo = Repository(tmp_path / "baru" / "scanner.db")

    tabel = {row[0] for row in repo.connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    repo.close()

    assert {"runs", "scan_results", "alerts"} <= tabel


def test_start_run_mengembalikan_id_yang_bertambah(repo):
    pertama = repo.start_run()
    kedua = repo.start_run()

    assert kedua > pertama


def test_finish_run_menyimpan_ringkasan(repo):
    run_id = repo.start_run()

    repo.finish_run(run_id, status="ok", scanned=5, candidates=2, alerts=1, notes="uji")

    baris = repo.connection.execute(
        "SELECT status, scanned, candidates, alerts, notes, finished_at FROM runs WHERE id=?",
        (run_id,),
    ).fetchone()
    assert baris[0] == "ok"
    assert baris[1:5] == (5, 2, 1, "uji")
    assert baris[5] is not None


def test_record_result_menyimpan_indikator_sebagai_json(repo):
    run_id = repo.start_run()
    result = ScanResult(
        symbol="BBRI.JK",
        decision=Decision.BUY_ALERT,
        reason="lolos",
        technical=_signal(),
        sentiment=_verdict(),
    )

    repo.record_result(run_id, result)

    baris = repo.connection.execute(
        "SELECT symbol, decision, close, indicators, sentiment_label, sentiment_score, as_of "
        "FROM scan_results WHERE run_id=?",
        (run_id,),
    ).fetchone()
    assert baris[0] == "BBRI.JK"
    assert baris[1] == "BUY_ALERT"
    assert baris[2] == pytest.approx(5000.0)
    assert json.loads(baris[3])["sma_fast"] == pytest.approx(5010.0)
    assert baris[4] == "POSITIF"
    assert baris[5] == pytest.approx(0.85)
    assert baris[6] == "2026-08-25"


def test_record_result_menerima_hasil_tanpa_teknikal(repo):
    run_id = repo.start_run()
    result = ScanResult(symbol="XXXX.JK", decision=Decision.SKIPPED_NO_DATA, reason="kosong")

    repo.record_result(run_id, result)

    baris = repo.connection.execute(
        "SELECT decision, close, sentiment_label FROM scan_results WHERE symbol='XXXX.JK'"
    ).fetchone()
    assert baris == ("SKIPPED_NO_DATA", None, None)


def test_recently_alerted_false_bila_belum_pernah(repo):
    assert repo.recently_alerted("BBRI.JK", cooldown_days=5) is False


def test_recently_alerted_true_di_dalam_cooldown(repo):
    run_id = repo.start_run()
    kemarin = datetime(2026, 8, 24, 18, 0, 0)
    repo.record_alert(run_id, "BBRI.JK", date(2026, 8, 24), 5000.0, {"a": 1}, sent_at=kemarin)

    hasil = repo.recently_alerted("BBRI.JK", cooldown_days=5, now=datetime(2026, 8, 25, 18, 0, 0))

    assert hasil is True


def test_recently_alerted_false_setelah_cooldown_lewat(repo):
    run_id = repo.start_run()
    lama = datetime(2026, 8, 1, 18, 0, 0)
    repo.record_alert(run_id, "BBRI.JK", date(2026, 8, 1), 5000.0, {"a": 1}, sent_at=lama)

    hasil = repo.recently_alerted("BBRI.JK", cooldown_days=5, now=datetime(2026, 8, 25, 18, 0, 0))

    assert hasil is False


def test_recently_alerted_hanya_melihat_simbol_yang_diminta(repo):
    run_id = repo.start_run()
    repo.record_alert(run_id, "TLKM.JK", date(2026, 8, 25), 3000.0, {},
                      sent_at=datetime(2026, 8, 25, 18, 0, 0))

    hasil = repo.recently_alerted("BBRI.JK", cooldown_days=5, now=datetime(2026, 8, 25, 19, 0, 0))

    assert hasil is False


def test_record_alert_menyimpan_payload_json(repo):
    run_id = repo.start_run()

    repo.record_alert(run_id, "BBRI.JK", date(2026, 8, 25), 5000.0, {"rules": ["sma_cross"]})

    payload = repo.connection.execute(
        "SELECT payload FROM alerts WHERE symbol='BBRI.JK'"
    ).fetchone()[0]
    assert json.loads(payload)["rules"] == ["sma_cross"]
```

- [ ] **Step 3: Jalankan tes, pastikan GAGAL**

Run: `python -m pytest tests/storage/test_repository.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ihsg_screener.storage.repository'`

- [ ] **Step 4: Tulis `src/ihsg_screener/storage/repository.py`**

```python
"""Akses SQLite untuk riwayat scan, alert, dan deduplikasi."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from ..models import ScanResult

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class Repository:
    """Pembungkus SQLite. Skema diterapkan otomatis saat inisialisasi."""

    def __init__(self, db_path: str | Path) -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.connection.commit()

    def start_run(self, started_at: datetime | None = None) -> int:
        moment = (started_at or datetime.now()).isoformat(timespec="seconds")
        cursor = self.connection.execute(
            "INSERT INTO runs (started_at, status) VALUES (?, 'running')", (moment,)
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def finish_run(
        self,
        run_id: int,
        status: str,
        scanned: int,
        candidates: int,
        alerts: int,
        notes: str = "",
    ) -> None:
        self.connection.execute(
            "UPDATE runs SET finished_at=?, status=?, scanned=?, candidates=?, "
            "alerts=?, notes=? WHERE id=?",
            (
                datetime.now().isoformat(timespec="seconds"),
                status,
                scanned,
                candidates,
                alerts,
                notes,
                run_id,
            ),
        )
        self.connection.commit()

    def record_result(
        self, run_id: int, result: ScanResult, as_of: date | None = None
    ) -> None:
        technical = result.technical
        sentiment = result.sentiment
        effective_as_of = as_of or (technical.as_of if technical else None)

        self.connection.execute(
            "INSERT INTO scan_results (run_id, symbol, as_of, decision, reason, close, "
            "indicators, sentiment_label, sentiment_score, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                result.symbol,
                effective_as_of.isoformat() if effective_as_of else None,
                result.decision.value,
                result.reason,
                technical.close if technical else None,
                json.dumps(technical.indicators) if technical else None,
                sentiment.label.value if sentiment else None,
                sentiment.score if sentiment else None,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        self.connection.commit()

    def record_alert(
        self,
        run_id: int,
        symbol: str,
        as_of: date,
        close: float,
        payload: dict,
        sent_at: datetime | None = None,
    ) -> None:
        self.connection.execute(
            "INSERT INTO alerts (run_id, symbol, as_of, close, payload, sent_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                run_id,
                symbol,
                as_of.isoformat(),
                close,
                json.dumps(payload, ensure_ascii=False),
                (sent_at or datetime.now()).isoformat(timespec="seconds"),
            ),
        )
        self.connection.commit()

    def recently_alerted(
        self, symbol: str, cooldown_days: int, now: datetime | None = None
    ) -> bool:
        """True bila simbol sudah dialert dalam cooldown_days hari terakhir."""
        cutoff = (now or datetime.now()) - timedelta(days=cooldown_days)
        row = self.connection.execute(
            "SELECT 1 FROM alerts WHERE symbol=? AND sent_at >= ? LIMIT 1",
            (symbol, cutoff.isoformat(timespec="seconds")),
        ).fetchone()
        return row is not None

    def close(self) -> None:
        self.connection.close()
```

- [ ] **Step 5: Jalankan tes, pastikan LULUS**

Run: `python -m pytest tests/storage/test_repository.py -v`
Expected: 10 tes PASS

- [ ] **Step 6: Commit**

```bash
git add src/ihsg_screener/storage/ tests/storage/
git commit -m "feat: penyimpanan SQLite untuk riwayat scan, alert, dan dedup"
```

---

### Task 8: Provider data pasar (yfinance)

**Files:**
- Create: `src/ihsg_screener/providers/market.py`
- Test: `tests/providers/test_market.py`

**Interfaces:**
- Consumes: `errors.StaleDataError` (Task 1)
- Produces:
  - `market.MarketDataProvider(lookback_days: int, min_bars: int, downloader: Callable | None = None)` — `downloader` disuntikkan pada tes; bawaannya `yfinance.download`
  - `.fetch_batch(symbols: Sequence[str]) -> dict[str, pd.DataFrame]` — hanya berisi simbol yang lolos validasi
  - `market.split_frames(raw: pd.DataFrame, symbols: Sequence[str]) -> dict[str, pd.DataFrame]`
  - `market.is_valid_frame(df: pd.DataFrame, min_bars: int) -> bool`
  - `market.latest_bar_date(frames: Mapping[str, pd.DataFrame]) -> date | None`
  - `market.assert_fresh(latest: date | None, today: date, max_age_days: int) -> None` — melempar `StaleDataError`

**Jebakan yang ditangani:** `yf.download()` batch tidak melempar exception untuk simbol tidak valid — kolomnya kembali berisi NaN seluruhnya. Validasi karena itu eksplisit, bukan lewat try/except.

- [ ] **Step 1: Tulis tes gagal**

Buat `tests/providers/__init__.py` (kosong) dan `tests/providers/test_market.py`:

```python
from datetime import date

import numpy as np
import pandas as pd
import pytest

from ihsg_screener.errors import StaleDataError
from ihsg_screener.providers import market


def _multi_frame(symbols, panjang=30, nan_untuk=()):
    idx = pd.date_range("2026-07-01", periods=panjang, freq="B")
    kolom = pd.MultiIndex.from_product([symbols, ["Open", "High", "Low", "Close", "Volume"]])
    data = pd.DataFrame(1000.0, index=idx, columns=kolom)
    for simbol in nan_untuk:
        data[simbol] = np.nan
    return data


def test_split_frames_memisahkan_per_simbol():
    raw = _multi_frame(["BBRI.JK", "TLKM.JK"])

    frames = market.split_frames(raw, ["BBRI.JK", "TLKM.JK"])

    assert set(frames) == {"BBRI.JK", "TLKM.JK"}
    assert "Close" in frames["BBRI.JK"].columns
    assert len(frames["BBRI.JK"]) == 30


def test_is_valid_frame_menolak_bar_yang_kurang():
    df = pd.DataFrame({"Close": [1.0, 2.0]}, index=pd.date_range("2026-08-01", periods=2))

    assert market.is_valid_frame(df, min_bars=10) is False


def test_is_valid_frame_menolak_close_terakhir_nan():
    df = pd.DataFrame(
        {"Close": [1.0] * 19 + [np.nan]}, index=pd.date_range("2026-07-01", periods=20)
    )

    assert market.is_valid_frame(df, min_bars=10) is False


def test_is_valid_frame_menerima_data_yang_sehat():
    df = pd.DataFrame({"Close": [1.0] * 20}, index=pd.date_range("2026-07-01", periods=20))

    assert market.is_valid_frame(df, min_bars=10) is True


def test_fetch_batch_membuang_simbol_yang_seluruhnya_nan():
    raw = _multi_frame(["BBRI.JK", "GHOST.JK"], nan_untuk=["GHOST.JK"])
    provider = market.MarketDataProvider(
        lookback_days=180, min_bars=10, downloader=lambda **_: raw
    )

    frames = provider.fetch_batch(["BBRI.JK", "GHOST.JK"])

    assert set(frames) == {"BBRI.JK"}


def test_fetch_batch_mengembalikan_dict_kosong_bila_unduhan_kosong():
    provider = market.MarketDataProvider(
        lookback_days=180, min_bars=10, downloader=lambda **_: pd.DataFrame()
    )

    assert provider.fetch_batch(["BBRI.JK"]) == {}


def test_fetch_batch_menangani_satu_simbol_tanpa_multiindex():
    idx = pd.date_range("2026-07-01", periods=30, freq="B")
    tunggal = pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 1}, index=idx)
    provider = market.MarketDataProvider(
        lookback_days=180, min_bars=10, downloader=lambda **_: tunggal
    )

    frames = provider.fetch_batch(["BBRI.JK"])

    assert list(frames) == ["BBRI.JK"]
    assert len(frames["BBRI.JK"]) == 30


def test_latest_bar_date_mengambil_tanggal_terbaru():
    idx_a = pd.date_range("2026-08-01", periods=5, freq="B")
    idx_b = pd.date_range("2026-08-10", periods=5, freq="B")
    frames = {
        "A": pd.DataFrame({"Close": [1.0] * 5}, index=idx_a),
        "B": pd.DataFrame({"Close": [1.0] * 5}, index=idx_b),
    }

    assert market.latest_bar_date(frames) == idx_b[-1].date()


def test_latest_bar_date_none_bila_kosong():
    assert market.latest_bar_date({}) is None


def test_assert_fresh_meloloskan_data_hari_ini():
    market.assert_fresh(date(2026, 8, 25), today=date(2026, 8, 25), max_age_days=4)


def test_assert_fresh_menolak_data_basi():
    with pytest.raises(StaleDataError, match="basi"):
        market.assert_fresh(date(2026, 8, 1), today=date(2026, 8, 25), max_age_days=4)


def test_assert_fresh_menolak_ketiadaan_data():
    with pytest.raises(StaleDataError, match="tidak ada"):
        market.assert_fresh(None, today=date(2026, 8, 25), max_age_days=4)
```

- [ ] **Step 2: Jalankan tes, pastikan GAGAL**

Run: `python -m pytest tests/providers/test_market.py -v`
Expected: FAIL — `ImportError: cannot import name 'market'`

- [ ] **Step 3: Tulis `src/ihsg_screener/providers/market.py`**

```python
"""Pengambilan data OHLCV EOD lewat yfinance, dengan validasi eksplisit.

yf.download() batch tidak melempar exception untuk simbol tidak valid atau
delisted: kolomnya kembali berisi NaN seluruhnya. Karena itu setiap frame
divalidasi secara eksplisit, bukan mengandalkan try/except.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Callable, Mapping, Sequence

import pandas as pd

from ..errors import StaleDataError

logger = logging.getLogger(__name__)


def _default_downloader(**kwargs) -> pd.DataFrame:
    import yfinance as yf

    return yf.download(**kwargs)


def split_frames(
    raw: pd.DataFrame, symbols: Sequence[str]
) -> dict[str, pd.DataFrame]:
    """Pecah hasil unduhan menjadi satu DataFrame per simbol."""
    if raw is None or raw.empty:
        return {}

    if not isinstance(raw.columns, pd.MultiIndex):
        return {symbols[0]: raw.dropna(how="all")} if len(symbols) == 1 else {}

    frames: dict[str, pd.DataFrame] = {}
    level = raw.columns.get_level_values(0)
    for symbol in symbols:
        if symbol not in level:
            continue
        frames[symbol] = raw[symbol].dropna(how="all")
    return frames


def is_valid_frame(df: pd.DataFrame, min_bars: int) -> bool:
    """True bila frame punya cukup bar dan harga penutupan terakhir bukan NaN."""
    if df is None or df.empty or "Close" not in df.columns:
        return False
    close = df["Close"].dropna()
    if len(close) < min_bars:
        return False
    return not pd.isna(df["Close"].iloc[-1])


def latest_bar_date(frames: Mapping[str, pd.DataFrame]) -> date | None:
    """Tanggal bar terbaru di seluruh frame, atau None bila tidak ada."""
    tanggal = [df.index[-1].date() for df in frames.values() if len(df)]
    return max(tanggal) if tanggal else None


def assert_fresh(latest: date | None, today: date, max_age_days: int) -> None:
    """Melempar StaleDataError bila bar terbaru terlalu lama.

    Menggantikan pemeliharaan kalender libur IDX: akhir pekan, libur nasional,
    dan cuti bersama semuanya tertangani oleh satu pemeriksaan umur data ini.
    """
    if latest is None:
        raise StaleDataError("tidak ada data pasar yang dapat digunakan")
    umur = (today - latest).days
    if umur > max_age_days:
        raise StaleDataError(
            f"data pasar basi: bar terbaru {latest} berumur {umur} hari "
            f"(maksimum {max_age_days})"
        )


class MarketDataProvider:
    """Mengambil OHLCV untuk banyak simbol dalam satu panggilan batch."""

    def __init__(
        self,
        lookback_days: int,
        min_bars: int,
        downloader: Callable[..., pd.DataFrame] | None = None,
    ) -> None:
        self.lookback_days = lookback_days
        self.min_bars = min_bars
        self._download = downloader or _default_downloader

    def fetch_batch(self, symbols: Sequence[str]) -> dict[str, pd.DataFrame]:
        """Unduh seluruh simbol sekaligus; kembalikan hanya yang lolos validasi."""
        if not symbols:
            return {}

        raw = self._download(
            tickers=list(symbols),
            period=f"{self.lookback_days}d",
            interval="1d",
            group_by="ticker",
            auto_adjust=False,
            progress=False,
            threads=True,
        )

        frames = split_frames(raw, list(symbols))
        valid: dict[str, pd.DataFrame] = {}
        for symbol, df in frames.items():
            if is_valid_frame(df, self.min_bars):
                valid[symbol] = df
            else:
                logger.warning("Data %s tidak valid atau tidak cukup; dilewati", symbol)
        return valid
```

- [ ] **Step 4: Jalankan tes, pastikan LULUS**

Run: `python -m pytest tests/providers/test_market.py -v`
Expected: 12 tes PASS

- [ ] **Step 5: Commit**

```bash
git add src/ihsg_screener/providers/market.py tests/providers/
git commit -m "feat: provider yfinance batch dengan validasi dan cek kesegaran data"
```

---

### Task 9: Provider berita (NewsAPI)

**Files:**
- Create: `src/ihsg_screener/providers/news.py`
- Test: `tests/providers/test_news.py`

**Interfaces:**
- Consumes: `models.Article`, `models.Ticker` (Task 2), `config.NewsConfig`, `config.HttpConfig`, `errors.QuotaExceededError` (Task 1)
- Produces:
  - `news.build_query(ticker: Ticker) -> str`
  - `news.NewsProvider(api_key: str, news_config: NewsConfig, http_config: HttpConfig, session=None)` — `session` disuntikkan pada tes
  - `.fetch(ticker: Ticker) -> list[Article]`
  - `.requests_used: int` (properti baca-saja)

**Perilaku kuota:** setiap panggilan `fetch` menambah penghitung. Bila penghitung sudah mencapai `max_requests_per_run`, `fetch` melempar `QuotaExceededError` **tanpa** menyentuh jaringan. HTTP 429 juga dinaikkan menjadi `QuotaExceededError`.

- [ ] **Step 1: Tulis tes gagal**

Buat `tests/providers/test_news.py`:

```python
import pytest

from ihsg_screener.config import HttpConfig, NewsConfig
from ihsg_screener.errors import QuotaExceededError
from ihsg_screener.models import Ticker
from ihsg_screener.providers import news

BBRI = Ticker(symbol="BBRI.JK", name="Bank Rakyat Indonesia", aliases=("BBRI", "BRI"))
NEWS_CFG = NewsConfig(page_size=3, max_requests_per_run=2, lookback_days=3, language="id")
HTTP_CFG = HttpConfig(timeout_seconds=15, retries=1, backoff_base_seconds=0)


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {"status": "ok", "articles": []}

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        return self._responses.pop(0) if self._responses else FakeResponse()


def _payload(*judul):
    return {
        "status": "ok",
        "articles": [
            {
                "title": j,
                "description": f"deskripsi {j}",
                "url": f"https://contoh.id/{i}",
                "source": {"name": "Detikcom"},
                "publishedAt": "2026-08-25T10:00:00Z",
            }
            for i, j in enumerate(judul)
        ],
    }


def test_build_query_menggabungkan_nama_dan_alias():
    query = news.build_query(BBRI)

    assert '"Bank Rakyat Indonesia"' in query
    assert "BBRI" in query
    assert " OR " in query


def test_fetch_mengurai_artikel():
    session = FakeSession(FakeResponse(payload=_payload("BBRI cetak laba")))
    provider = news.NewsProvider("kunci", NEWS_CFG, HTTP_CFG, session=session)

    articles = provider.fetch(BBRI)

    assert len(articles) == 1
    assert articles[0].title == "BBRI cetak laba"
    assert articles[0].source == "Detikcom"
    assert articles[0].url == "https://contoh.id/0"


def test_fetch_selalu_menetapkan_timeout():
    session = FakeSession(FakeResponse(payload=_payload("a")))
    provider = news.NewsProvider("kunci", NEWS_CFG, HTTP_CFG, session=session)

    provider.fetch(BBRI)

    assert session.calls[0]["timeout"] == 15


def test_fetch_mengirim_filter_bahasa_dan_page_size():
    session = FakeSession(FakeResponse(payload=_payload("a")))
    provider = news.NewsProvider("kunci", NEWS_CFG, HTTP_CFG, session=session)

    provider.fetch(BBRI)
    params = session.calls[0]["params"]

    assert params["language"] == "id"
    assert params["pageSize"] == 3
    assert params["sortBy"] == "publishedAt"


def test_fetch_tidak_pernah_menaruh_api_key_di_url():
    session = FakeSession(FakeResponse(payload=_payload("a")))
    provider = news.NewsProvider("rahasia", NEWS_CFG, HTTP_CFG, session=session)

    provider.fetch(BBRI)

    assert "rahasia" not in session.calls[0]["url"]
    assert "rahasia" not in str(session.calls[0]["params"])


def test_fetch_menangani_deskripsi_null():
    payload = _payload("a")
    payload["articles"][0]["description"] = None
    session = FakeSession(FakeResponse(payload=payload))
    provider = news.NewsProvider("kunci", NEWS_CFG, HTTP_CFG, session=session)

    assert provider.fetch(BBRI)[0].description == ""


def test_requests_used_bertambah_tiap_panggilan():
    session = FakeSession(FakeResponse(payload=_payload("a")), FakeResponse(payload=_payload("b")))
    provider = news.NewsProvider("kunci", NEWS_CFG, HTTP_CFG, session=session)

    provider.fetch(BBRI)
    provider.fetch(BBRI)

    assert provider.requests_used == 2


def test_budget_habis_melempar_tanpa_memanggil_jaringan():
    session = FakeSession(FakeResponse(payload=_payload("a")), FakeResponse(payload=_payload("b")))
    provider = news.NewsProvider("kunci", NEWS_CFG, HTTP_CFG, session=session)
    provider.fetch(BBRI)
    provider.fetch(BBRI)

    with pytest.raises(QuotaExceededError, match="budget"):
        provider.fetch(BBRI)

    assert len(session.calls) == 2


def test_http_429_dinaikkan_menjadi_quota_exceeded():
    session = FakeSession(FakeResponse(status_code=429, payload={"message": "limit"}))
    provider = news.NewsProvider("kunci", NEWS_CFG, HTTP_CFG, session=session)

    with pytest.raises(QuotaExceededError):
        provider.fetch(BBRI)


def test_status_error_dari_newsapi_menghasilkan_daftar_kosong():
    session = FakeSession(FakeResponse(payload={"status": "error", "message": "buruk"}))
    provider = news.NewsProvider("kunci", NEWS_CFG, HTTP_CFG, session=session)

    assert provider.fetch(BBRI) == []
```

- [ ] **Step 2: Jalankan tes, pastikan GAGAL**

Run: `python -m pytest tests/providers/test_news.py -v`
Expected: FAIL — `ImportError: cannot import name 'news'`

- [ ] **Step 3: Tulis `src/ihsg_screener/providers/news.py`**

```python
"""Klien NewsAPI dengan budget kuota lokal dan retry transien."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..config import HttpConfig, NewsConfig
from ..errors import QuotaExceededError
from ..models import Article, Ticker

logger = logging.getLogger(__name__)

ENDPOINT = "https://newsapi.org/v2/everything"


def build_query(ticker: Ticker) -> str:
    """Bangun query dari nama perusahaan dan alias.

    Pencarian hanya dengan kode emiten memberi recall buruk untuk berita
    Indonesia, sehingga nama perusahaan selalu disertakan.
    """
    terms = [f'"{ticker.name}"']
    for alias in (ticker.code, *ticker.aliases):
        if alias and alias not in terms:
            terms.append(alias)
    return " OR ".join(dict.fromkeys(terms))


class NewsProvider:
    """Mengambil berita berbahasa Indonesia per emiten."""

    def __init__(
        self,
        api_key: str,
        news_config: NewsConfig,
        http_config: HttpConfig,
        session=None,
    ) -> None:
        self._api_key = api_key
        self._news = news_config
        self._http = http_config
        self._session = session or self._default_session()
        self._requests_used = 0
        # API key dikirim lewat header, tidak pernah lewat URL atau query, agar
        # tidak bocor ke log akses server maupun log aplikasi.
        if hasattr(self._session, "headers"):
            self._session.headers.update({"X-Api-Key": api_key})

    @staticmethod
    def _default_session():
        import requests

        return requests.Session()

    @property
    def requests_used(self) -> int:
        return self._requests_used

    def fetch(self, ticker: Ticker) -> list[Article]:
        """Ambil artikel terbaru untuk satu emiten.

        Melempar QuotaExceededError bila budget lokal habis, tanpa menyentuh
        jaringan, sehingga sistem berhenti pada batas yang kita tetapkan
        sendiri alih-alih pada penolakan NewsAPI di tengah jalan.
        """
        if self._requests_used >= self._news.max_requests_per_run:
            raise QuotaExceededError(
                f"budget permintaan NewsAPI habis "
                f"({self._news.max_requests_per_run} per run)"
            )

        params = {
            "q": build_query(ticker),
            "language": self._news.language,
            "sortBy": "publishedAt",
            "pageSize": self._news.page_size,
            "from": (date.today() - timedelta(days=self._news.lookback_days)).isoformat(),
        }

        self._requests_used += 1
        response = self._get(params)

        if response.status_code == 429:
            raise QuotaExceededError("NewsAPI membalas 429: batas permintaan tercapai")
        if response.status_code != 200:
            logger.warning(
                "NewsAPI membalas %s untuk %s", response.status_code, ticker.symbol
            )
            return []

        payload = response.json()
        if payload.get("status") != "ok":
            logger.warning(
                "NewsAPI status=%s untuk %s: %s",
                payload.get("status"),
                ticker.symbol,
                payload.get("message"),
            )
            return []

        return [self._to_article(raw) for raw in payload.get("articles", [])]

    def _get(self, params: dict):
        @retry(
            stop=stop_after_attempt(self._http.retries),
            wait=wait_exponential(multiplier=self._http.backoff_base_seconds),
            retry=retry_if_exception_type(OSError),
            reraise=True,
        )
        def _call():
            return self._session.get(
                ENDPOINT,
                params=params,
                timeout=self._http.timeout_seconds,
            )

        return _call()

    @staticmethod
    def _to_article(raw: dict) -> Article:
        source = raw.get("source") or {}
        return Article(
            title=raw.get("title") or "",
            description=raw.get("description") or "",
            url=raw.get("url") or "",
            source=source.get("name") or "",
            published_at=raw.get("publishedAt") or "",
        )
```

- [ ] **Step 4: Jalankan tes, pastikan LULUS**

Run: `python -m pytest tests/providers/test_news.py -v`
Expected: 10 tes PASS

- [ ] **Step 5: Commit**

```bash
git add src/ihsg_screener/providers/news.py tests/providers/test_news.py
git commit -m "feat: provider NewsAPI dengan budget kuota lokal dan retry"
```

---

### Task 10: Engine sentimen IndoBERT

**Files:**
- Create: `src/ihsg_screener/providers/sentiment_engine.py`
- Test: `tests/providers/test_sentiment_engine.py`

**Interfaces:**
- Consumes: `models.SentimentLabel` (Task 2), `errors.LabelMappingError` (Task 1)
- Produces:
  - `sentiment_engine.map_labels(id2label: Mapping[int | str, str]) -> dict[str, SentimentLabel]` — **fungsi murni, diuji tanpa torch**
  - `sentiment_engine.SentimentEngine(model_name: str, batch_size: int = 8, pipeline_factory: Callable | None = None)`
  - `.classify(texts: Sequence[str]) -> list[tuple[SentimentLabel, float]]`
  - `.is_loaded: bool`

**Perilaku label:** `map_labels` memetakan nama label model ke `SentimentLabel`. Label generik (`LABEL_0`, `LABEL_1`, …) **ditolak** dengan `LabelMappingError` — menebak arah label akan membalik seluruh gate sentimen tanpa memunculkan error apa pun di log.

**Pemuatan malas:** pipeline hanya dibangun pada panggilan `classify` pertama.

- [ ] **Step 1: Tulis tes gagal**

Buat `tests/providers/test_sentiment_engine.py`:

```python
import pytest

from ihsg_screener.errors import LabelMappingError
from ihsg_screener.models import SentimentLabel
from ihsg_screener.providers import sentiment_engine as se


def test_map_labels_menerima_label_bahasa_inggris():
    hasil = se.map_labels({0: "negative", 1: "neutral", 2: "positive"})

    assert hasil["negative"] is SentimentLabel.NEGATIF
    assert hasil["neutral"] is SentimentLabel.NETRAL
    assert hasil["positive"] is SentimentLabel.POSITIF


def test_map_labels_menerima_label_bahasa_indonesia():
    hasil = se.map_labels({0: "negatif", 1: "netral", 2: "positif"})

    assert hasil["positif"] is SentimentLabel.POSITIF


def test_map_labels_tidak_peduli_besar_kecil_huruf():
    assert se.map_labels({0: "POSITIVE"})["positive"] is SentimentLabel.POSITIF


def test_map_labels_menerima_label_dua_kelas():
    hasil = se.map_labels({0: "negative", 1: "positive"})

    assert set(hasil.values()) == {SentimentLabel.NEGATIF, SentimentLabel.POSITIF}


def test_map_labels_menolak_label_generik():
    with pytest.raises(LabelMappingError, match="LABEL_0"):
        se.map_labels({0: "LABEL_0", 1: "LABEL_1", 2: "LABEL_2"})


def test_map_labels_menolak_pemetaan_kosong():
    with pytest.raises(LabelMappingError, match="kosong"):
        se.map_labels({})


def test_engine_tidak_memuat_model_sampai_classify_dipanggil():
    engine = se.SentimentEngine("model-palsu", pipeline_factory=lambda name: _pipeline_palsu())

    assert engine.is_loaded is False


def test_classify_mengembalikan_label_dan_skor():
    engine = se.SentimentEngine("model-palsu", pipeline_factory=lambda name: _pipeline_palsu())

    hasil = engine.classify(["berita bagus", "berita buruk"])

    assert hasil[0] == (SentimentLabel.POSITIF, pytest.approx(0.91))
    assert hasil[1] == (SentimentLabel.NEGATIF, pytest.approx(0.88))
    assert engine.is_loaded is True


def test_classify_meneruskan_parameter_truncation_512():
    pipeline = _pipeline_palsu()
    engine = se.SentimentEngine("model-palsu", pipeline_factory=lambda name: pipeline)

    engine.classify(["teks"])

    assert pipeline.last_kwargs["truncation"] is True
    assert pipeline.last_kwargs["max_length"] == 512


def test_classify_daftar_kosong_tidak_memuat_model():
    engine = se.SentimentEngine("model-palsu", pipeline_factory=lambda name: _pipeline_palsu())

    assert engine.classify([]) == []
    assert engine.is_loaded is False


class _PipelinePalsu:
    def __init__(self):
        self.model = type("M", (), {"config": type("C", (), {"id2label": {0: "negative", 1: "positive"}})()})()
        self.last_kwargs = None

    def __call__(self, texts, **kwargs):
        self.last_kwargs = kwargs
        jawaban = {"berita bagus": ("positive", 0.91), "berita buruk": ("negative", 0.88)}
        return [
            {"label": jawaban.get(t, ("positive", 0.5))[0], "score": jawaban.get(t, ("positive", 0.5))[1]}
            for t in texts
        ]


def _pipeline_palsu():
    return _PipelinePalsu()
```

- [ ] **Step 2: Jalankan tes, pastikan GAGAL**

Run: `python -m pytest tests/providers/test_sentiment_engine.py -v`
Expected: FAIL — `ImportError: cannot import name 'sentiment_engine'`

- [ ] **Step 3: Tulis `src/ihsg_screener/providers/sentiment_engine.py`**

```python
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
```

- [ ] **Step 4: Jalankan tes, pastikan LULUS**

Run: `python -m pytest tests/providers/test_sentiment_engine.py -v`
Expected: 10 tes PASS

- [ ] **Step 5: Tambahkan tes integrasi yang dilewati secara default**

Tambahkan di akhir `tests/providers/test_sentiment_engine.py`:

```python
@pytest.mark.integration
def test_model_asli_dapat_dimuat_dan_labelnya_terpetakan():
    """Verifikasi asumsi §17.1 spec. Jalankan: pytest -m integration"""
    import yaml

    cfg = yaml.safe_load(open("config/settings.yaml", encoding="utf-8"))
    engine = se.SentimentEngine(cfg["sentiment"]["model"])

    hasil = engine.classify(["Kinerja perusahaan sangat baik dan laba meningkat tajam"])

    assert hasil[0][0] in set(SentimentLabel)
    assert 0.0 <= hasil[0][1] <= 1.0
```

- [ ] **Step 6: Verifikasi asumsi model asli**

Run: `python -m pytest tests/providers/test_sentiment_engine.py -m integration -v`

Hasil yang mungkin:
- **PASS** — asumsi §17.1 spec terkonfirmasi, lanjutkan.
- **FAIL karena model tidak ditemukan** — cari model IndoBERT sentimen alternatif di HuggingFace Hub, ubah `sentiment.model` di `config/settings.yaml`, jalankan ulang. Tidak ada kode yang perlu diubah.
- **FAIL dengan `LabelMappingError`** — model memakai label generik. Periksa kartu modelnya untuk urutan label yang benar, lalu tambahkan aliasnya ke `_ALIASES`. **Jangan menebak urutannya.**

Catat hasilnya sebagai komentar di `config/settings.yaml` di atas kunci `model`.

- [ ] **Step 7: Commit**

```bash
git add src/ihsg_screener/providers/sentiment_engine.py tests/providers/test_sentiment_engine.py config/settings.yaml
git commit -m "feat: engine IndoBERT dengan pemuatan malas dan verifikasi label"
```

---

### Task 11: Notifier Telegram

**Files:**
- Create: `src/ihsg_screener/notifiers/telegram.py`
- Test: `tests/notifiers/test_telegram.py`

**Interfaces:**
- Consumes: `models.TechnicalSignal`, `models.SentimentVerdict`, `models.Ticker` (Task 2), `config.HttpConfig` (Task 1), `errors.NotifierError` (Task 1)
- Produces:
  - `telegram.format_alert(ticker: Ticker, signal: TechnicalSignal, verdict: SentimentVerdict) -> str` — **fungsi murni**
  - `telegram.TelegramNotifier(bot_token: str, chat_id: str, http_config: HttpConfig, session=None)`
  - `.send(text: str) -> None` — melempar `NotifierError` bila status bukan 200

- [ ] **Step 1: Tulis tes gagal**

Buat `tests/notifiers/__init__.py` (kosong) dan `tests/notifiers/test_telegram.py`:

```python
from datetime import date

import pytest

from ihsg_screener.config import HttpConfig
from ihsg_screener.errors import NotifierError
from ihsg_screener.models import (
    Article,
    ArticleSentiment,
    SentimentLabel,
    SentimentVerdict,
    TechnicalSignal,
    Ticker,
)
from ihsg_screener.notifiers import telegram

HTTP_CFG = HttpConfig(timeout_seconds=15, retries=1, backoff_base_seconds=0)
BBRI = Ticker(symbol="BBRI.JK", name="Bank Rakyat Indonesia", aliases=("BBRI",))


def _signal():
    return TechnicalSignal(
        symbol="BBRI.JK",
        is_bullish=True,
        close=5000.0,
        as_of=date(2026, 8, 25),
        indicators={"sma_fast": 5010.5, "sma_slow": 4900.25},
        passed_rules=("sma_cross",),
        failed_rules=(),
    )


def _verdict():
    artikel = Article(
        title="BBRI cetak laba", description="", url="https://contoh.id/1",
        source="Detikcom", published_at="2026-08-25T10:00:00Z",
    )
    return SentimentVerdict(
        label=SentimentLabel.POSITIF,
        score=0.85,
        analyzed_count=2,
        rejected_count=1,
        per_article=(ArticleSentiment(article=artikel, label=SentimentLabel.POSITIF, score=0.9),),
    )


class FakeResponse:
    def __init__(self, status_code=200, text="ok"):
        self.status_code = status_code
        self.text = text


class FakeSession:
    def __init__(self, response=None):
        self.response = response or FakeResponse()
        self.calls = []

    def post(self, url, json=None, timeout=None):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        return self.response


def test_format_alert_memuat_simbol_dan_harga():
    pesan = telegram.format_alert(BBRI, _signal(), _verdict())

    assert "BBRI.JK" in pesan
    assert "5,000.00" in pesan
    assert "BUY ALERT" in pesan


def test_format_alert_memuat_nama_perusahaan_dan_tanggal():
    pesan = telegram.format_alert(BBRI, _signal(), _verdict())

    assert "Bank Rakyat Indonesia" in pesan
    assert "2026-08-25" in pesan


def test_format_alert_memuat_aturan_yang_lulus_dan_nilainya():
    pesan = telegram.format_alert(BBRI, _signal(), _verdict())

    assert "sma_cross" in pesan
    assert "sma_fast" in pesan


def test_format_alert_memuat_ringkasan_sentimen():
    pesan = telegram.format_alert(BBRI, _signal(), _verdict())

    assert "POSITIF" in pesan
    assert "0.85" in pesan
    assert "2" in pesan


def test_format_alert_memuat_tautan_artikel():
    pesan = telegram.format_alert(BBRI, _signal(), _verdict())

    assert "https://contoh.id/1" in pesan


def test_send_memanggil_endpoint_sendmessage_dengan_timeout():
    session = FakeSession()
    notifier = telegram.TelegramNotifier("token123", "chat456", HTTP_CFG, session=session)

    notifier.send("halo")

    assert session.calls[0]["url"] == "https://api.telegram.org/bottoken123/sendMessage"
    assert session.calls[0]["json"]["chat_id"] == "chat456"
    assert session.calls[0]["json"]["text"] == "halo"
    assert session.calls[0]["timeout"] == 15


def test_send_melempar_notifier_error_pada_status_bukan_200():
    session = FakeSession(FakeResponse(status_code=400, text="bad request"))
    notifier = telegram.TelegramNotifier("token123", "chat456", HTTP_CFG, session=session)

    with pytest.raises(NotifierError, match="400"):
        notifier.send("halo")


def test_send_tidak_membocorkan_token_di_pesan_error():
    session = FakeSession(FakeResponse(status_code=401, text="unauthorized"))
    notifier = telegram.TelegramNotifier("token-rahasia", "chat456", HTTP_CFG, session=session)

    with pytest.raises(NotifierError) as exc:
        notifier.send("halo")

    assert "token-rahasia" not in str(exc.value)
```

- [ ] **Step 2: Jalankan tes, pastikan GAGAL**

Run: `python -m pytest tests/notifiers/test_telegram.py -v`
Expected: FAIL — `ImportError: cannot import name 'telegram'`

- [ ] **Step 3: Tulis `src/ihsg_screener/notifiers/telegram.py`**

```python
"""Pengiriman alert ke Telegram Bot API."""

from __future__ import annotations

import logging

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..config import HttpConfig
from ..errors import NotifierError
from ..models import SentimentVerdict, TechnicalSignal, Ticker

logger = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"


def format_alert(
    ticker: Ticker, signal: TechnicalSignal, verdict: SentimentVerdict
) -> str:
    """Susun pesan alert. Fungsi murni sehingga isinya dapat diuji langsung."""
    indikator = "\n".join(
        f"  • {nama}: {nilai:,.2f}" for nama, nilai in sorted(signal.indicators.items())
    )
    tautan = "\n".join(
        f"  • [{item.label.value} {item.score:.2f}] {item.article.url}"
        for item in verdict.per_article
    )

    baris = [
        "🚀 *BUY ALERT*",
        "",
        f"*{ticker.symbol}* — {ticker.name}",
        f"Tanggal data: {signal.as_of.isoformat()}",
        f"Harga penutupan: {signal.close:,.2f}",
        "",
        f"*Teknikal:* BULLISH ({', '.join(signal.passed_rules)})",
        indikator,
        "",
        f"*Sentimen:* {verdict.label.value} "
        f"(skor {verdict.score:.2f}, {verdict.analyzed_count} artikel)",
        tautan,
    ]
    return "\n".join(b for b in baris if b is not None)


class TelegramNotifier:
    """Mengirim pesan ke satu Chat ID lewat Telegram Bot API."""

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        http_config: HttpConfig,
        session=None,
    ) -> None:
        self._token = bot_token
        self._chat_id = chat_id
        self._http = http_config
        self._session = session or self._default_session()

    @staticmethod
    def _default_session():
        import requests

        return requests.Session()

    def send(self, text: str) -> None:
        """Kirim pesan. Melempar NotifierError bila Telegram tidak membalas 200."""
        url = f"{API_BASE}/bot{self._token}/sendMessage"
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }

        @retry(
            stop=stop_after_attempt(self._http.retries),
            wait=wait_exponential(multiplier=self._http.backoff_base_seconds),
            retry=retry_if_exception_type(OSError),
            reraise=True,
        )
        def _call():
            return self._session.post(url, json=payload, timeout=self._http.timeout_seconds)

        response = _call()
        if response.status_code != 200:
            # Token tidak pernah disertakan dalam pesan error agar tidak bocor ke log.
            raise NotifierError(
                f"Telegram membalas {response.status_code}: {response.text[:200]}"
            )
```

- [ ] **Step 4: Jalankan tes, pastikan LULUS**

Run: `python -m pytest tests/notifiers/test_telegram.py -v`
Expected: 8 tes PASS

- [ ] **Step 5: Commit**

```bash
git add src/ihsg_screener/notifiers/telegram.py tests/notifiers/
git commit -m "feat: notifier Telegram dengan format alert yang dapat diuji"
```

---

### Task 12: Orkestrator pipeline

**Files:**
- Create: `src/ihsg_screener/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: seluruh modul Task 2–11
- Produces:
  - `pipeline.PipelineDeps(market, news, engine_factory: Callable[[], SentimentEngine], notifier, repo)` — dataclass biasa (tidak frozen)
  - `pipeline.RunSummary(status: str, scanned: int, candidates: int, alerts: int, results: list[ScanResult], notes: str)`
  - `pipeline.run(tickers: Sequence[Ticker], settings: Settings, deps: PipelineDeps, *, dry_run: bool = False, force: bool = False, today: date | None = None) -> RunSummary`

**Urutan wajib** (§6 spec):
1. `market.fetch_batch` untuk seluruh simbol
2. `assert_fresh` pada bar terbaru → bila basi, `RunSummary(status="ok")` dengan catatan "tidak ada data baru"
3. `strategy.evaluate` per simbol
4. Saring bullish
5. **Dedup sebelum berita** — kandidat dalam cooldown menjadi `SKIPPED_DUPLICATE` tanpa menyentuh jaringan
6. `engine_factory()` dipanggil **hanya bila** masih ada kandidat
7. Per kandidat: berita → `prepare_articles` → `classify` → `aggregate`
8. Gate AND → kirim → catat

**Ketentuan:** `QuotaExceededError` menghentikan tahap berita; kandidat sisa menjadi `ERROR` dan status run menjadi `degraded`. Kegagalan Telegram membuat alert **tidak** dicatat ke tabel `alerts`. Saat `dry_run`, tidak ada pengiriman dan tidak ada penulisan ke DB. `run()` adalah pembungkus terluar (§13 spec): baris run dibuat di sana sehingga exception apa pun tetap menutupnya dengan status `fatal` sebelum dilempar ulang; alur sesungguhnya ada di `_scan()`.

- [ ] **Step 1: Tulis tes gagal — bagian gate**

Buat `tests/test_pipeline.py`:

```python
from datetime import date

import pandas as pd
import pytest

from ihsg_screener import pipeline
from ihsg_screener.config import (
    AlertsConfig,
    HttpConfig,
    NewsConfig,
    RuntimeConfig,
    SentimentConfig,
    Settings,
    Secrets,
)
from ihsg_screener.errors import QuotaExceededError
from ihsg_screener.models import Article, Decision, SentimentLabel, Ticker
from ihsg_screener.storage.repository import Repository

BBRI = Ticker(symbol="BBRI.JK", name="Bank Rakyat Indonesia", aliases=("BBRI", "BRI"))
TLKM = Ticker(symbol="TLKM.JK", name="Telkom Indonesia", aliases=("TLKM",))
HARI_INI = date(2026, 8, 25)


def _settings():
    return Settings(
        technical={
            "min_bars": 30,
            "lookback_days": 180,
            "rules": {"sma_cross": {"enabled": True, "fast": 5, "slow": 20}},
        },
        sentiment=SentimentConfig(
            model="m", articles_per_ticker=3, min_articles=1, min_avg_score=0.60,
            neutral_weight=0.0, veto_on_strong_negative=True,
            strong_negative_threshold=0.80, batch_size=8,
        ),
        news=NewsConfig(page_size=3, max_requests_per_run=40, lookback_days=3, language="id"),
        alerts=AlertsConfig(cooldown_days=5),
        http=HttpConfig(timeout_seconds=15, retries=1, backoff_base_seconds=0),
        runtime=RuntimeConfig(
            db_path=":memory:", log_dir="logs", lock_file="x.lock", max_data_age_days=4
        ),
        secrets=Secrets(newsapi_key="k", telegram_bot_token="t", telegram_chat_id="c"),
    )


def _frame(values, akhir=HARI_INI):
    idx = pd.bdate_range(end=pd.Timestamp(akhir), periods=len(values))
    return pd.DataFrame({"Close": [float(v) for v in values]}, index=idx)


NAIK = list(range(1, 61))
TURUN = list(range(60, 0, -1))


class FakeMarket:
    def __init__(self, frames):
        self.frames = frames

    def fetch_batch(self, symbols):
        return {s: f for s, f in self.frames.items() if s in symbols}


class FakeNews:
    def __init__(self, per_symbol=None, raise_quota_after=None):
        self.per_symbol = per_symbol or {}
        self.raise_quota_after = raise_quota_after
        self.calls = []

    def fetch(self, ticker):
        if self.raise_quota_after is not None and len(self.calls) >= self.raise_quota_after:
            raise QuotaExceededError("budget habis")
        self.calls.append(ticker.symbol)
        return self.per_symbol.get(ticker.symbol, [])


class FakeEngine:
    def __init__(self, hasil):
        self.hasil = hasil
        self.calls = 0

    def classify(self, texts):
        self.calls += 1
        return [self.hasil] * len(texts)


class FakeNotifier:
    def __init__(self, gagal=False):
        self.sent = []
        self.gagal = gagal

    def send(self, text):
        if self.gagal:
            from ihsg_screener.errors import NotifierError

            raise NotifierError("gagal kirim")
        self.sent.append(text)


def _artikel(judul="BBRI cetak laba besar"):
    return [Article(title=judul, description="Laba naik", url="https://contoh.id/1",
                    source="Detikcom", published_at="2026-08-25T10:00:00Z")]


@pytest.fixture()
def repo(tmp_path):
    r = Repository(tmp_path / "scanner.db")
    yield r
    r.close()


def _deps(market, news, engine, notifier, repo):
    dibuat = {"n": 0}

    def factory():
        dibuat["n"] += 1
        return engine

    deps = pipeline.PipelineDeps(
        market=market, news=news, engine_factory=factory, notifier=notifier, repo=repo
    )
    deps.engine_dibuat = dibuat
    return deps


def test_bullish_dan_positif_memicu_alert(repo):
    market = FakeMarket({"BBRI.JK": _frame(NAIK)})
    news = FakeNews({"BBRI.JK": _artikel()})
    engine = FakeEngine((SentimentLabel.POSITIF, 0.9))
    notifier = FakeNotifier()

    summary = pipeline.run([BBRI], _settings(), _deps(market, news, engine, notifier, repo), today=HARI_INI)

    assert summary.alerts == 1
    assert len(notifier.sent) == 1
    assert summary.results[0].decision is Decision.BUY_ALERT


def test_bullish_tetapi_negatif_tidak_memicu_alert(repo):
    market = FakeMarket({"BBRI.JK": _frame(NAIK)})
    news = FakeNews({"BBRI.JK": _artikel()})
    engine = FakeEngine((SentimentLabel.NEGATIF, 0.9))
    notifier = FakeNotifier()

    summary = pipeline.run([BBRI], _settings(), _deps(market, news, engine, notifier, repo), today=HARI_INI)

    assert summary.alerts == 0
    assert notifier.sent == []
    assert summary.results[0].decision is Decision.REJECTED_SENTIMENT


def test_tidak_bullish_tidak_menyentuh_berita(repo):
    market = FakeMarket({"BBRI.JK": _frame(TURUN)})
    news = FakeNews({"BBRI.JK": _artikel()})
    engine = FakeEngine((SentimentLabel.POSITIF, 0.9))
    notifier = FakeNotifier()

    summary = pipeline.run([BBRI], _settings(), _deps(market, news, engine, notifier, repo), today=HARI_INI)

    assert news.calls == []
    assert summary.results[0].decision is Decision.REJECTED_TECHNICAL


def test_model_tidak_dimuat_bila_tidak_ada_kandidat(repo):
    market = FakeMarket({"BBRI.JK": _frame(TURUN)})
    news = FakeNews()
    engine = FakeEngine((SentimentLabel.POSITIF, 0.9))
    deps = _deps(market, news, engine, FakeNotifier(), repo)

    pipeline.run([BBRI], _settings(), deps, today=HARI_INI)

    assert deps.engine_dibuat["n"] == 0
    assert engine.calls == 0


def test_dedup_mencegah_alert_kedua_dan_menghemat_kuota(repo):
    market = FakeMarket({"BBRI.JK": _frame(NAIK)})
    news = FakeNews({"BBRI.JK": _artikel()})
    engine = FakeEngine((SentimentLabel.POSITIF, 0.9))
    settings = _settings()

    pipeline.run([BBRI], settings, _deps(market, news, engine, FakeNotifier(), repo), today=HARI_INI)
    news_kedua = FakeNews({"BBRI.JK": _artikel()})
    summary = pipeline.run(
        [BBRI], settings, _deps(market, news_kedua, engine, FakeNotifier(), repo), today=HARI_INI
    )

    assert summary.alerts == 0
    assert news_kedua.calls == []
    assert summary.results[0].decision is Decision.SKIPPED_DUPLICATE


def test_force_mengabaikan_dedup(repo):
    market = FakeMarket({"BBRI.JK": _frame(NAIK)})
    engine = FakeEngine((SentimentLabel.POSITIF, 0.9))
    settings = _settings()

    pipeline.run([BBRI], settings, _deps(market, FakeNews({"BBRI.JK": _artikel()}), engine, FakeNotifier(), repo), today=HARI_INI)
    notifier = FakeNotifier()
    summary = pipeline.run(
        [BBRI], settings,
        _deps(market, FakeNews({"BBRI.JK": _artikel()}), engine, notifier, repo),
        force=True, today=HARI_INI,
    )

    assert summary.alerts == 1
    assert len(notifier.sent) == 1


def test_tanpa_artikel_relevan_menghasilkan_skipped_no_news(repo):
    market = FakeMarket({"BBRI.JK": _frame(NAIK)})
    news = FakeNews({"BBRI.JK": _artikel("IHSG ditutup menguat")})
    engine = FakeEngine((SentimentLabel.POSITIF, 0.9))

    summary = pipeline.run(
        [BBRI], _settings(), _deps(market, news, engine, FakeNotifier(), repo), today=HARI_INI
    )

    assert summary.results[0].decision is Decision.SKIPPED_NO_NEWS
    assert engine.calls == 0


def test_kuota_habis_membuat_run_degraded(repo):
    market = FakeMarket({"BBRI.JK": _frame(NAIK), "TLKM.JK": _frame(NAIK)})
    news = FakeNews({"BBRI.JK": _artikel(), "TLKM.JK": _artikel("TLKM cetak laba")},
                    raise_quota_after=1)
    engine = FakeEngine((SentimentLabel.POSITIF, 0.9))

    summary = pipeline.run(
        [BBRI, TLKM], _settings(), _deps(market, news, engine, FakeNotifier(), repo), today=HARI_INI
    )

    assert summary.status == "degraded"
    keputusan = {r.symbol: r.decision for r in summary.results}
    assert keputusan["TLKM.JK"] is Decision.ERROR


def test_data_basi_mengakhiri_run_lebih_awal(repo):
    market = FakeMarket({"BBRI.JK": _frame(NAIK, akhir=date(2026, 8, 1))})
    news = FakeNews()

    summary = pipeline.run(
        [BBRI], _settings(),
        _deps(market, news, FakeEngine((SentimentLabel.POSITIF, 0.9)), FakeNotifier(), repo),
        today=HARI_INI,
    )

    assert summary.status == "ok"
    assert summary.alerts == 0
    assert "basi" in summary.notes or "data baru" in summary.notes


def test_simbol_tanpa_data_menghasilkan_skipped_no_data(repo):
    market = FakeMarket({})

    summary = pipeline.run(
        [BBRI], _settings(),
        _deps(market, FakeNews(), FakeEngine((SentimentLabel.POSITIF, 0.9)), FakeNotifier(), repo),
        today=HARI_INI,
    )

    assert summary.results[0].decision is Decision.SKIPPED_NO_DATA
    # Nol data bukan hari libur, melainkan kegagalan: harus terlihat begitu.
    assert summary.status == "degraded"
    assert summary.scanned == 1


def test_kegagalan_telegram_tidak_mencatat_alert(repo):
    market = FakeMarket({"BBRI.JK": _frame(NAIK)})
    news = FakeNews({"BBRI.JK": _artikel()})
    engine = FakeEngine((SentimentLabel.POSITIF, 0.9))
    notifier = FakeNotifier(gagal=True)

    summary = pipeline.run(
        [BBRI], _settings(), _deps(market, news, engine, notifier, repo), today=HARI_INI
    )

    assert summary.alerts == 0
    assert summary.results[0].decision is Decision.ERROR
    jumlah = repo.connection.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    assert jumlah == 0


def test_dry_run_tidak_mengirim_dan_tidak_menulis_alert(repo):
    market = FakeMarket({"BBRI.JK": _frame(NAIK)})
    news = FakeNews({"BBRI.JK": _artikel()})
    engine = FakeEngine((SentimentLabel.POSITIF, 0.9))
    notifier = FakeNotifier()

    summary = pipeline.run(
        [BBRI], _settings(), _deps(market, news, engine, notifier, repo),
        dry_run=True, today=HARI_INI,
    )

    assert summary.results[0].decision is Decision.BUY_ALERT
    assert notifier.sent == []
    assert repo.connection.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 0
    assert repo.connection.execute("SELECT COUNT(*) FROM scan_results").fetchone()[0] == 0


def test_setiap_emiten_menghasilkan_tepat_satu_hasil(repo):
    market = FakeMarket({"BBRI.JK": _frame(NAIK), "TLKM.JK": _frame(TURUN)})
    news = FakeNews({"BBRI.JK": _artikel()})
    engine = FakeEngine((SentimentLabel.POSITIF, 0.9))

    summary = pipeline.run(
        [BBRI, TLKM], _settings(), _deps(market, news, engine, FakeNotifier(), repo), today=HARI_INI
    )

    assert len(summary.results) == 2
    assert {r.symbol for r in summary.results} == {"BBRI.JK", "TLKM.JK"}
    assert summary.scanned == 2


def test_exception_tak_terduga_tetap_menutup_baris_run(repo):
    class MarketMeledak:
        def fetch_batch(self, symbols):
            raise RuntimeError("koneksi putus")

    deps = _deps(MarketMeledak(), FakeNews(), FakeEngine((SentimentLabel.POSITIF, 0.9)),
                 FakeNotifier(), repo)

    with pytest.raises(RuntimeError):
        pipeline.run([BBRI], _settings(), deps, today=HARI_INI)

    baris = repo.connection.execute(
        "SELECT status, finished_at, notes FROM runs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert baris[0] == "fatal"
    assert baris[1] is not None
    assert "koneksi putus" in baris[2]
```

- [ ] **Step 2: Jalankan tes, pastikan GAGAL**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: FAIL — `ImportError: cannot import name 'pipeline'`

- [ ] **Step 3: Tulis `src/ihsg_screener/pipeline.py`**

```python
"""Orkestrator alur scan. Seluruh provider disuntikkan lewat PipelineDeps."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Sequence

from .config import Settings
from .core import sentiment as sentiment_core
from .core import strategy, textproc
from .errors import (
    InsufficientDataError,
    NotifierError,
    QuotaExceededError,
    StaleDataError,
)
from .models import (
    ArticleSentiment,
    Decision,
    ScanResult,
    SentimentLabel,
    Ticker,
)
from .notifiers.telegram import format_alert
from .providers import market as market_module

logger = logging.getLogger(__name__)


@dataclass
class PipelineDeps:
    market: Any
    news: Any
    engine_factory: Callable[[], Any]
    notifier: Any
    repo: Any


@dataclass
class RunSummary:
    status: str
    scanned: int
    candidates: int
    alerts: int
    results: list[ScanResult] = field(default_factory=list)
    notes: str = ""


def run(
    tickers: Sequence[Ticker],
    settings: Settings,
    deps: PipelineDeps,
    *,
    dry_run: bool = False,
    force: bool = False,
    today: date | None = None,
) -> RunSummary:
    """Jalankan satu siklus scan, dengan jaminan ringkasan run selalu tertulis.

    Baris run dibuat di sini agar exception apa pun tetap dapat menutupnya:
    kegagalan yang meninggalkan run berstatus 'running' selamanya adalah
    kegagalan yang tidak akan disadari selama berminggu-minggu.
    """
    run_id = None if dry_run else deps.repo.start_run()
    try:
        return _scan(
            tickers, settings, deps, run_id,
            dry_run=dry_run, force=force, today=today,
        )
    except Exception as exc:
        logger.exception("Run dihentikan oleh kesalahan tak terduga")
        if not dry_run:
            deps.repo.finish_run(run_id, "fatal", 0, 0, 0, f"exception: {exc}")
        raise


def _scan(
    tickers: Sequence[Ticker],
    settings: Settings,
    deps: PipelineDeps,
    run_id: int | None,
    *,
    dry_run: bool,
    force: bool,
    today: date | None,
) -> RunSummary:
    """Alur scan sesungguhnya.

    Urutan tahapannya menentukan biaya: dedup dijalankan sebelum pengambilan
    berita agar kuota tidak terbakar untuk alert yang akan dibuang, dan model
    sentimen baru dimuat setelah dipastikan ada kandidat.
    """
    today = today or date.today()
    results: list[ScanResult] = []

    def catat(result: ScanResult) -> None:
        results.append(result)
        if not dry_run:
            deps.repo.record_result(run_id, result)

    # Tahap 1-2: unduh batch, lalu periksa kesegaran bar terbaru.
    frames = deps.market.fetch_batch([t.symbol for t in tickers])

    # Nol frame bukan hari libur bursa: pada hari libur yfinance tetap
    # mengembalikan data, hanya bertanggal lama. Tidak ada data sama sekali
    # berarti unduhannya yang rusak, dan itu harus terlihat sebagai kegagalan
    # per emiten, bukan sebagai run kosong yang berstatus normal.
    if not frames:
        for ticker in tickers:
            catat(
                ScanResult(ticker.symbol, Decision.SKIPPED_NO_DATA, "data tidak tersedia")
            )
        notes = "tidak ada satu pun data emiten yang berhasil diunduh"
        logger.error(notes)
        if not dry_run:
            deps.repo.finish_run(run_id, "degraded", len(tickers), 0, 0, notes)
        return RunSummary(
            status="degraded",
            scanned=len(tickers),
            candidates=0,
            alerts=0,
            results=results,
            notes=notes,
        )

    try:
        market_module.assert_fresh(
            market_module.latest_bar_date(frames),
            today=today,
            max_age_days=settings.runtime.max_data_age_days,
        )
    except StaleDataError as exc:
        notes = f"tidak ada data baru: {exc}"
        logger.info(notes)
        if not dry_run:
            deps.repo.finish_run(run_id, "ok", 0, 0, 0, notes)
        return RunSummary(status="ok", scanned=0, candidates=0, alerts=0, notes=notes)

    # Tahap 3-4: evaluasi teknikal, saring kandidat bullish.
    kandidat: list[tuple[Ticker, Any]] = []
    for ticker in tickers:
        df = frames.get(ticker.symbol)
        if df is None:
            catat(ScanResult(ticker.symbol, Decision.SKIPPED_NO_DATA, "data tidak tersedia"))
            continue
        try:
            signal = strategy.evaluate(ticker.symbol, df, settings.technical)
        except InsufficientDataError as exc:
            catat(ScanResult(ticker.symbol, Decision.SKIPPED_NO_DATA, str(exc)))
            continue
        except Exception as exc:  # aturan rusak tidak boleh menjatuhkan run
            logger.exception("Evaluasi teknikal %s gagal", ticker.symbol)
            catat(ScanResult(ticker.symbol, Decision.ERROR, f"teknikal gagal: {exc}"))
            continue

        if not signal.is_bullish:
            catat(
                ScanResult(
                    ticker.symbol,
                    Decision.REJECTED_TECHNICAL,
                    f"aturan gagal: {', '.join(signal.failed_rules) or 'tidak ada aturan aktif'}",
                    technical=signal,
                )
            )
            continue
        kandidat.append((ticker, signal))

    # Tahap 5: dedup SEBELUM menyentuh jaringan berita.
    tersaring: list[tuple[Ticker, Any]] = []
    for ticker, signal in kandidat:
        if not force and deps.repo.recently_alerted(
            ticker.symbol, settings.alerts.cooldown_days
        ):
            catat(
                ScanResult(
                    ticker.symbol,
                    Decision.SKIPPED_DUPLICATE,
                    f"sudah dialert dalam {settings.alerts.cooldown_days} hari terakhir",
                    technical=signal,
                )
            )
            continue
        tersaring.append((ticker, signal))

    status = "ok"
    alerts = 0

    # Tahap 6: model dimuat hanya bila masih ada kandidat.
    engine = deps.engine_factory() if tersaring else None

    kuota_habis = False
    for ticker, signal in tersaring:
        if kuota_habis:
            catat(ScanResult(ticker.symbol, Decision.ERROR, "budget NewsAPI habis", technical=signal))
            continue

        try:
            articles = deps.news.fetch(ticker)
        except QuotaExceededError as exc:
            kuota_habis = True
            status = "degraded"
            logger.warning("Kuota berita habis: %s", exc)
            catat(ScanResult(ticker.symbol, Decision.ERROR, f"budget NewsAPI habis: {exc}", technical=signal))
            continue
        except Exception as exc:
            logger.exception("Pengambilan berita %s gagal", ticker.symbol)
            catat(ScanResult(ticker.symbol, Decision.ERROR, f"berita gagal: {exc}", technical=signal))
            continue

        siap = textproc.prepare_articles(
            articles[: settings.sentiment.articles_per_ticker], ticker
        )
        if not siap:
            catat(
                ScanResult(
                    ticker.symbol,
                    Decision.SKIPPED_NO_NEWS,
                    "tidak ada artikel relevan",
                    technical=signal,
                )
            )
            continue

        try:
            skor = engine.classify([teks for _, teks in siap])
        except Exception as exc:
            logger.exception("Inferensi %s gagal", ticker.symbol)
            catat(ScanResult(ticker.symbol, Decision.ERROR, f"inferensi gagal: {exc}", technical=signal))
            continue

        per_artikel = [
            ArticleSentiment(article=artikel, label=label, score=nilai)
            for (artikel, _), (label, nilai) in zip(siap, skor)
        ]
        verdict = sentiment_core.aggregate(per_artikel, settings.sentiment)

        # Tahap 7: gate AND.
        if verdict.label is not SentimentLabel.POSITIF:
            catat(
                ScanResult(
                    ticker.symbol,
                    Decision.REJECTED_SENTIMENT,
                    f"sentimen {verdict.label.value} (skor {verdict.score})",
                    technical=signal,
                    sentiment=verdict,
                )
            )
            continue

        pesan = format_alert(ticker, signal, verdict)
        if dry_run:
            logger.info("[dry-run] alert untuk %s:\n%s", ticker.symbol, pesan)
            catat(
                ScanResult(
                    ticker.symbol, Decision.BUY_ALERT, "dry-run", technical=signal, sentiment=verdict
                )
            )
            alerts += 1
            continue

        try:
            deps.notifier.send(pesan)
        except NotifierError as exc:
            status = "degraded"
            logger.error("Pengiriman Telegram %s gagal: %s", ticker.symbol, exc)
            # Alert TIDAK dicatat: run berikutnya harus mencobanya lagi.
            catat(ScanResult(ticker.symbol, Decision.ERROR, f"telegram gagal: {exc}",
                             technical=signal, sentiment=verdict))
            continue

        deps.repo.record_alert(
            run_id,
            ticker.symbol,
            signal.as_of,
            signal.close,
            {
                "passed_rules": list(signal.passed_rules),
                "indicators": signal.indicators,
                "sentiment": verdict.label.value,
                "sentiment_score": verdict.score,
            },
        )
        alerts += 1
        catat(
            ScanResult(
                ticker.symbol, Decision.BUY_ALERT, "teknikal bullish dan sentimen positif",
                technical=signal, sentiment=verdict
            )
        )

    summary = RunSummary(
        status=status,
        scanned=len(tickers),
        candidates=len(kandidat),
        alerts=alerts,
        results=results,
        notes="",
    )
    if not dry_run:
        deps.repo.finish_run(
            run_id, status, summary.scanned, summary.candidates, summary.alerts
        )
    return summary
```

- [ ] **Step 4: Jalankan tes, pastikan LULUS**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: 14 tes PASS

- [ ] **Step 5: Jalankan seluruh suite**

Run: `python -m pytest tests/ -v`
Expected: seluruh tes PASS, tanpa akses jaringan

- [ ] **Step 6: Commit**

```bash
git add src/ihsg_screener/pipeline.py tests/test_pipeline.py
git commit -m "feat: orkestrator pipeline dengan gate AND dan pemuatan model malas"
```

---

### Task 13: CLI, logging, lock file, exit code

**Files:**
- Create: `src/ihsg_screener/cli.py`
- Create: `src/ihsg_screener/runlock.py`
- Test: `tests/test_cli.py`, `tests/test_runlock.py`

**Interfaces:**
- Consumes: seluruh modul sebelumnya
- Produces:
  - `runlock.RunLock(path: str | Path)` — context manager; melempar `runlock.AlreadyRunningError` bila lock aktif
  - `cli.build_parser() -> argparse.ArgumentParser`
  - `cli.setup_logging(log_dir: str | Path, verbose: bool) -> None`
  - `cli.filter_tickers(tickers: list[Ticker], only: str | None) -> list[Ticker]`
  - `cli.main(argv: Sequence[str] | None = None) -> int` — mengembalikan exit code

**Exit code:** `0` normal, `1` terdegradasi (`ScreenerError` yang tertangani, atau `summary.status == "degraded"`), `2` fatal (`ConfigError`, `LabelMappingError`, lock aktif, atau exception tak terduga).

- [ ] **Step 1: Tulis tes gagal untuk lock**

Buat `tests/test_runlock.py`:

```python
import pytest

from ihsg_screener.runlock import AlreadyRunningError, RunLock


def test_lock_membuat_dan_menghapus_file(tmp_path):
    path = tmp_path / "scanner.lock"

    with RunLock(path):
        assert path.exists()

    assert not path.exists()


def test_lock_kedua_ditolak_selama_yang_pertama_aktif(tmp_path):
    path = tmp_path / "scanner.lock"

    with RunLock(path):
        with pytest.raises(AlreadyRunningError):
            with RunLock(path):
                pass


def test_lock_dilepas_meski_terjadi_exception(tmp_path):
    path = tmp_path / "scanner.lock"

    with pytest.raises(ValueError):
        with RunLock(path):
            raise ValueError("boom")

    assert not path.exists()


def test_lock_membuat_direktori_induk(tmp_path):
    path = tmp_path / "dalam" / "scanner.lock"

    with RunLock(path):
        assert path.exists()
```

- [ ] **Step 2: Jalankan tes, pastikan GAGAL**

Run: `python -m pytest tests/test_runlock.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ihsg_screener.runlock'`

- [ ] **Step 3: Tulis `src/ihsg_screener/runlock.py`**

```python
"""Lock file sederhana agar dua run terjadwal tidak tumpang tindih."""

from __future__ import annotations

import os
from pathlib import Path

from .errors import ScreenerError


class AlreadyRunningError(ScreenerError):
    """Run lain masih berjalan."""


class RunLock:
    """Context manager berbasis pembuatan file eksklusif."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def __enter__(self) -> "RunLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise AlreadyRunningError(
                f"Run lain sedang berjalan (lock: {self.path}). "
                "Bila yakin tidak ada, hapus file tersebut secara manual."
            ) from exc
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.path.unlink(missing_ok=True)
```

- [ ] **Step 4: Jalankan tes, pastikan LULUS**

Run: `python -m pytest tests/test_runlock.py -v`
Expected: 4 tes PASS

- [ ] **Step 5: Tulis tes gagal untuk CLI**

Buat `tests/test_cli.py`:

```python
import pytest

from ihsg_screener import cli
from ihsg_screener.models import Ticker

BBRI = Ticker(symbol="BBRI.JK", name="Bank Rakyat Indonesia", aliases=("BBRI",))
TLKM = Ticker(symbol="TLKM.JK", name="Telkom Indonesia", aliases=("TLKM",))


def test_parser_default_tidak_dry_run_dan_tidak_force():
    args = cli.build_parser().parse_args([])

    assert args.dry_run is False
    assert args.force is False
    assert args.verbose is False
    assert args.tickers is None


def test_parser_menerima_seluruh_flag():
    args = cli.build_parser().parse_args(
        ["--dry-run", "--force", "--verbose", "--tickers", "BBRI,TLKM"]
    )

    assert args.dry_run is True
    assert args.force is True
    assert args.verbose is True
    assert args.tickers == "BBRI,TLKM"


def test_filter_tickers_none_mengembalikan_seluruhnya():
    assert cli.filter_tickers([BBRI, TLKM], None) == [BBRI, TLKM]


def test_filter_tickers_mencocokkan_kode_tanpa_suffix():
    assert cli.filter_tickers([BBRI, TLKM], "BBRI") == [BBRI]


def test_filter_tickers_mencocokkan_simbol_penuh():
    assert cli.filter_tickers([BBRI, TLKM], "TLKM.JK") == [TLKM]


def test_filter_tickers_menerima_daftar_dan_spasi():
    assert cli.filter_tickers([BBRI, TLKM], " bbri , tlkm ") == [BBRI, TLKM]


def test_filter_tickers_menolak_kode_yang_tidak_ada_di_watchlist():
    from ihsg_screener.errors import ConfigError

    with pytest.raises(ConfigError, match="XXXX"):
        cli.filter_tickers([BBRI, TLKM], "XXXX")


def test_exit_code_untuk_status():
    assert cli.exit_code_for("ok") == 0
    assert cli.exit_code_for("degraded") == 1
```

- [ ] **Step 6: Jalankan tes, pastikan GAGAL**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ihsg_screener.cli'`

- [ ] **Step 7: Tulis `src/ihsg_screener/cli.py`**

```python
"""Entry point CLI: memuat konfigurasi, merangkai provider, menjalankan pipeline."""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv

from .config import load_settings, load_watchlist
from .errors import ConfigError, LabelMappingError, ScreenerError
from .models import Ticker
from .notifiers.telegram import TelegramNotifier
from .pipeline import PipelineDeps, run
from .providers.market import MarketDataProvider
from .providers.news import NewsProvider
from .providers.sentiment_engine import SentimentEngine
from .runlock import AlreadyRunningError, RunLock
from .storage.repository import Repository

logger = logging.getLogger("ihsg_screener")

EXIT_OK = 0
EXIT_DEGRADED = 1
EXIT_FATAL = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ihsg-screener",
        description="Screener EOD saham IDX: gate teknikal + sentimen berita IndoBERT",
    )
    parser.add_argument("--config", default="config/settings.yaml", help="Lokasi settings.yaml")
    parser.add_argument("--watchlist", default="config/watchlist.yaml", help="Lokasi watchlist.yaml")
    parser.add_argument("--dry-run", action="store_true",
                        help="Jalankan penuh tanpa mengirim Telegram dan tanpa menulis DB")
    parser.add_argument("--tickers", default=None,
                        help="Batasi ke emiten tertentu, dipisah koma (mis. BBRI,TLKM)")
    parser.add_argument("--force", action="store_true", help="Abaikan dedup cooldown")
    parser.add_argument("--verbose", action="store_true", help="Log level DEBUG")
    return parser


def setup_logging(log_dir: str | Path, verbose: bool) -> None:
    path = Path(log_dir)
    path.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.handlers.clear()

    fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    root.addHandler(stream)

    berkas = logging.handlers.TimedRotatingFileHandler(
        path / "scanner.log", when="midnight", backupCount=30, encoding="utf-8"
    )
    berkas.setFormatter(fmt)
    root.addHandler(berkas)


def filter_tickers(tickers: list[Ticker], only: str | None) -> list[Ticker]:
    """Saring watchlist berdasarkan argumen --tickers. Menolak kode tak dikenal."""
    if not only:
        return tickers

    diminta = [bagian.strip().upper() for bagian in only.split(",") if bagian.strip()]
    indeks = {t.symbol.upper(): t for t in tickers}
    indeks.update({t.code.upper(): t for t in tickers})

    hasil: list[Ticker] = []
    for kode in diminta:
        if kode not in indeks:
            raise ConfigError(f"Emiten '{kode}' tidak ada di watchlist")
        if indeks[kode] not in hasil:
            hasil.append(indeks[kode])
    return hasil


def exit_code_for(status: str) -> int:
    return EXIT_DEGRADED if status == "degraded" else EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv()

    try:
        settings = load_settings(Path(args.config))
        tickers = filter_tickers(load_watchlist(Path(args.watchlist)), args.tickers)
    except ConfigError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return EXIT_FATAL

    setup_logging(settings.runtime.log_dir, args.verbose)
    logger.info("Memindai %d emiten (dry_run=%s, force=%s)", len(tickers), args.dry_run, args.force)

    repo = Repository(settings.runtime.db_path)
    try:
        with RunLock(settings.runtime.lock_file):
            deps = PipelineDeps(
                market=MarketDataProvider(
                    lookback_days=settings.technical["lookback_days"],
                    min_bars=settings.technical["min_bars"],
                ),
                news=NewsProvider(
                    settings.secrets.newsapi_key, settings.news, settings.http
                ),
                engine_factory=lambda: SentimentEngine(
                    settings.sentiment.model, settings.sentiment.batch_size
                ),
                notifier=TelegramNotifier(
                    settings.secrets.telegram_bot_token,
                    settings.secrets.telegram_chat_id,
                    settings.http,
                ),
                repo=repo,
            )
            summary = run(tickers, settings, deps, dry_run=args.dry_run, force=args.force)
    except AlreadyRunningError as exc:
        logger.error("%s", exc)
        return EXIT_FATAL
    except LabelMappingError as exc:
        logger.error("Model sentimen tidak dapat dipakai: %s", exc)
        return EXIT_FATAL
    except ScreenerError as exc:
        logger.exception("Run gagal: %s", exc)
        return EXIT_DEGRADED
    except Exception:
        # pipeline.run() sudah menutup baris run dengan status 'fatal'; di sini
        # tinggal memastikan penjadwal ikut melihat kegagalannya lewat exit code.
        logger.exception("Kesalahan tak terduga menghentikan run")
        return EXIT_FATAL
    finally:
        repo.close()

    logger.info(
        "Selesai: status=%s dipindai=%d kandidat=%d alert=%d %s",
        summary.status, summary.scanned, summary.candidates, summary.alerts, summary.notes,
    )
    return exit_code_for(summary.status)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 8: Jalankan tes, pastikan LULUS**

Run: `python -m pytest tests/test_cli.py tests/test_runlock.py -v`
Expected: 12 tes PASS

- [ ] **Step 9: Commit**

```bash
git add src/ihsg_screener/cli.py src/ihsg_screener/runlock.py tests/test_cli.py tests/test_runlock.py
git commit -m "feat: CLI dengan dry-run, lock file, logging berotasi, dan exit code"
```

---

### Task 14: Penjaga batas arsitektur, README, dan verifikasi akhir

**Files:**
- Create: `tests/test_architecture.py`
- Create: `README.md`
- Create: `run_scanner.bat`
- Test: seluruh suite

**Interfaces:**
- Consumes: seluruh modul
- Produces: `run_scanner.bat` untuk Windows Task Scheduler

- [ ] **Step 1: Tulis tes penjaga batas arsitektur**

Buat `tests/test_architecture.py`:

```python
"""Menegakkan aturan struktural spec: core/ tidak boleh menyentuh I/O."""

import ast
from pathlib import Path

import pytest

CORE = Path(__file__).resolve().parents[1] / "src" / "ihsg_screener" / "core"
TERLARANG = {"yfinance", "requests", "transformers", "torch", "sqlite3", "urllib"}


def _modul_yang_diimpor(path: Path) -> set[str]:
    pohon = ast.parse(path.read_text(encoding="utf-8"))
    hasil: set[str] = set()
    for node in ast.walk(pohon):
        if isinstance(node, ast.Import):
            hasil.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            hasil.add(node.module.split(".")[0])
    return hasil


@pytest.mark.parametrize("path", sorted(CORE.glob("*.py")), ids=lambda p: p.name)
def test_core_tidak_mengimpor_lapisan_io(path):
    pelanggaran = _modul_yang_diimpor(path) & TERLARANG

    assert not pelanggaran, (
        f"{path.name} mengimpor {sorted(pelanggaran)}. "
        "Logika keputusan sedang bocor ke lapisan I/O."
    )


def test_core_memuat_seluruh_modul_yang_dijanjikan_spec():
    nama = {p.stem for p in CORE.glob("*.py")} - {"__init__"}

    assert nama == {"indicators", "strategy", "textproc", "sentiment"}
```

- [ ] **Step 2: Jalankan tes penjaga**

Run: `python -m pytest tests/test_architecture.py -v`
Expected: PASS. Bila gagal, pindahkan impor yang melanggar ke `providers/`.

- [ ] **Step 3: Tulis `run_scanner.bat`**

```bat
@echo off
REM Wrapper untuk Windows Task Scheduler. Jadwalkan 18:00-19:00 WIB, Senin-Jumat.
cd /d C:\xampp\htdocs\Scrapping
python -m ihsg_screener.cli %*
exit /b %ERRORLEVEL%
```

- [ ] **Step 4: Tulis `README.md`**

````markdown
# IHSG Screener

Screener harian saham Bursa Efek Indonesia. Mengirim BUY ALERT ke Telegram hanya
bila kondisi teknikal bullish **dan** sentimen berita positif menurut IndoBERT.

Ini screener pasca-market untuk ditinjau manusia, bukan sistem eksekusi order.

## Instalasi

```bash
python -m pip install -e ".[dev]"
copy .env.example .env
```

Isi `.env` dengan API key NewsAPI, token bot Telegram, dan Chat ID tujuan.

## Konfigurasi

- `config/watchlist.yaml` — daftar emiten beserta nama perusahaan dan alias untuk
  pencarian berita. Nama perusahaan wajib: mencari hanya dengan kode emiten
  memberi recall berita yang buruk.
- `config/settings.yaml` — parameter strategi, ambang sentimen, cooldown, budget
  kuota, timeout. Semua yang biasa disetel ada di sini; kode tidak perlu disentuh.

Mengaktifkan indikator tambahan cukup mengubah `enabled: true` pada aturan yang
diinginkan di bawah `technical.rules`. Emiten dinyatakan bullish hanya bila
seluruh aturan aktif lulus.

## Penggunaan

```bash
python -m ihsg_screener.cli --dry-run          # tanpa kirim & tanpa tulis DB
python -m ihsg_screener.cli --tickers BBRI     # batasi ke emiten tertentu
python -m ihsg_screener.cli --force            # abaikan cooldown dedup
python -m ihsg_screener.cli                    # run sesungguhnya
```

Gunakan `--dry-run` setiap kali mengubah parameter strategi: hasilnya terlihat
tanpa mengotori riwayat maupun mengirim notifikasi.

## Exit code

| Kode | Arti |
|---|---|
| 0 | Normal (termasuk hari libur bursa: tidak ada data baru) |
| 1 | Selesai tetapi terdegradasi (mis. kuota NewsAPI habis) |
| 2 | Fatal (konfigurasi tidak valid, model tidak dapat dipakai, run lain aktif, kesalahan tak terduga) |

## Penjadwalan

Windows Task Scheduler, jalankan `run_scanner.bat` pukul 18:00 WIB Senin–Jumat.
IDX tutup pukul 16:00 dan data EOD butuh waktu mengendap; menjalankan pukul 16:05
berisiko memperoleh bar yang belum final.

Hari libur bursa tidak perlu didaftarkan: sistem memeriksa umur bar terbaru dan
berhenti lebih awal bila datanya belum diperbarui.

Di Linux/VPS:

```cron
0 18 * * 1-5 cd /path/ke/Scrapping && python -m ihsg_screener.cli >> logs/cron.log 2>&1
```

## Pengujian

```bash
python -m pytest                      # seluruh tes, tanpa jaringan
python -m pytest -m integration       # verifikasi model & API asli
```

Tidak ada tes biasa yang menyentuh jaringan.

## Arsitektur

```
providers/  → menyentuh dunia luar (yfinance, NewsAPI, IndoBERT)
core/       → logika murni, tanpa I/O — di sinilah keputusan dibuat
notifiers/  → Telegram
storage/    → SQLite: riwayat scan, alert, dedup
pipeline.py → merangkai semuanya; provider disuntikkan sebagai argumen
```

`core/` tidak boleh mengimpor pustaka jaringan; aturan ini ditegakkan oleh
`tests/test_architecture.py`.

Design lengkap: `docs/superpowers/specs/2026-08-25-ihsg-screener-design.md`
````

- [ ] **Step 5: Jalankan seluruh suite**

Run: `python -m pytest tests/ -v`
Expected: seluruh tes PASS

- [ ] **Step 6: Verifikasi gagal-anggun tanpa konfigurasi**

Run: `python -m ihsg_screener.cli --config config/tidak-ada.yaml`
Expected: exit code `2`, pesan `FATAL:` yang jelas di stderr, **tanpa traceback**

Periksa exit code:
```bash
python -m ihsg_screener.cli --config config/tidak-ada.yaml; echo "exit=$?"
```

- [ ] **Step 7: Verifikasi dry-run end-to-end**

Isi `.env` dengan kredensial asli, lalu:

Run: `python -m ihsg_screener.cli --dry-run --verbose`

Expected:
- Log menunjukkan unduhan batch, evaluasi teknikal per emiten, dan keputusan
- Tidak ada pesan terkirim ke Telegram
- `data/scanner.db` tidak bertambah baris: verifikasi dengan
  `python -c "import sqlite3;print(sqlite3.connect('data/scanner.db').execute('SELECT COUNT(*) FROM scan_results').fetchone())"`
- Exit code `0` (atau `1` bila kuota berita habis)

- [ ] **Step 8: Verifikasi run sesungguhnya dan dedup**

Run: `python -m ihsg_screener.cli --verbose`

Bila ada emiten yang lolos kedua gate, satu pesan masuk ke Telegram dan satu baris
tercatat di tabel `alerts`. Jalankan perintah yang sama sekali lagi:

Expected: emiten yang sama menghasilkan `SKIPPED_DUPLICATE` dan tidak ada pesan
kedua yang terkirim.

Bila tidak ada emiten yang lolos, uji jalur pengiriman dengan menurunkan sementara
`sentiment.min_avg_score` di `config/settings.yaml`, jalankan ulang, lalu
kembalikan nilainya.

- [ ] **Step 9: Commit**

```bash
git add tests/test_architecture.py README.md run_scanner.bat
git commit -m "feat: penjaga batas arsitektur, README, dan wrapper penjadwalan"
```

---

## Kriteria selesai

Seluruh butir §18 spec:

- [ ] `python -m pytest` lulus seluruhnya tanpa akses jaringan
- [ ] `--dry-run` menghasilkan keputusan yang benar untuk watchlist penuh
- [ ] Satu alert nyata terkirim ke Telegram dan tercatat di tabel `alerts`
- [ ] Run kedua di hari yang sama tidak mengirim alert duplikat
- [ ] Menjalankan tanpa konfigurasi valid berakhir dengan exit code `2` dan pesan jelas tanpa traceback
- [ ] README memuat langkah instalasi, konfigurasi, dan penjadwalan
