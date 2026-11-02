from datetime import date

import pandas as pd
import pytest

from ihsg_screener import pipeline
from ihsg_screener.config import (
    AlertsConfig,
    HttpConfig,
    NewsConfig,
    RuntimeConfig,
    Secrets,
    SentimentConfig,
    Settings,
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
