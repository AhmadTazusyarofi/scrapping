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


def test_setup_logging_membungkam_pustaka_pihak_ketiga_meski_verbose(tmp_path):
    import logging

    cli.setup_logging(tmp_path / "logs", verbose=True)

    assert logging.getLogger().level == logging.DEBUG
    for bising in ("httpcore", "httpx", "urllib3", "transformers"):
        assert logging.getLogger(bising).level == logging.WARNING, bising


def test_render_results_menampilkan_simbol_alasan_dan_keputusan():
    from datetime import date

    from ihsg_screener.models import Decision, ScanResult, TechnicalSignal

    signal = TechnicalSignal(
        symbol="BBRI.JK", is_bullish=True, close=3180.0, as_of=date(2026, 8, 25),
        indicators={"sma_fast": 3142.0, "sma_slow": 3067.5},
        passed_rules=("sma_cross",), failed_rules=(),
    )
    hasil = [
        ScanResult("BBRI.JK", Decision.SKIPPED_NO_NEWS, "tidak ada artikel relevan", technical=signal),
        ScanResult("TLKM.JK", Decision.REJECTED_TECHNICAL, "aturan gagal: sma_cross"),
    ]

    teks = cli.render_results(hasil)

    assert "BBRI.JK" in teks
    assert "SKIPPED_NO_NEWS" in teks
    assert "tidak ada artikel relevan" in teks
    assert "TLKM.JK" in teks
    assert "REJECTED_TECHNICAL" in teks
    assert "3,180" in teks or "3180" in teks


def test_render_results_menangani_daftar_kosong():
    assert cli.render_results([]) == "(tidak ada hasil)"


def _settings_dengan_news(**kw):
    import dataclasses

    from ihsg_screener.config import (
        AlertsConfig, HttpConfig, NewsConfig, RuntimeConfig, Secrets,
        SentimentConfig, Settings,
    )

    news = NewsConfig(
        page_size=3, max_requests_per_run=40, lookback_days=3, language="id", **kw
    )
    return Settings(
        technical={"min_bars": 60, "lookback_days": 180, "rules": {}},
        sentiment=SentimentConfig(
            model="m", articles_per_ticker=3, min_articles=1, min_avg_score=0.6,
            neutral_weight=0.0, veto_on_strong_negative=True,
            strong_negative_threshold=0.8, batch_size=8,
        ),
        news=news,
        alerts=AlertsConfig(cooldown_days=5),
        http=HttpConfig(timeout_seconds=15, retries=1, backoff_base_seconds=0),
        runtime=RuntimeConfig(db_path=":memory:", log_dir="logs",
                              lock_file="x.lock", max_data_age_days=4),
        secrets=Secrets(newsapi_key="k", telegram_bot_token="t", telegram_chat_id="c"),
    )


def test_build_news_provider_memilih_newsapi():
    from ihsg_screener.providers.news import NewsProvider

    p = cli.build_news_provider(_settings_dengan_news(source="newsapi"))

    assert isinstance(p, NewsProvider)


def test_build_news_provider_memilih_rss():
    from ihsg_screener.providers.rss_news import RssNewsProvider

    p = cli.build_news_provider(
        _settings_dengan_news(source="rss", feeds=("https://a.id/rss",), max_age_hours=48)
    )

    assert isinstance(p, RssNewsProvider)
    assert p.feeds == ["https://a.id/rss"]


# --- Encoding stdout (bug Windows) -----------------------------------------
# Pesan alert memuat emoji dan bullet. Konsol Windows memakai cp1252, sehingga
# StreamHandler gagal meng-encode-nya dan logging membuang pesannya diam-diam.

class _StreamPalsu:
    def __init__(self, bisa_reconfigure=True):
        self.dipanggil = None
        if not bisa_reconfigure:
            del self.reconfigure

    def reconfigure(self, **kw):
        self.dipanggil = kw


def test_amankan_stream_menyetel_utf8():
    s = _StreamPalsu()

    cli.amankan_stream(s)

    assert s.dipanggil["encoding"] == "utf-8"
    assert s.dipanggil["errors"] == "replace"


def test_amankan_stream_tidak_meledak_pada_stream_tanpa_reconfigure():
    class Polos:
        pass

    cli.amankan_stream(Polos())  # tidak boleh melempar


def test_amankan_stream_menelan_error_reconfigure():
    class Rewel:
        def reconfigure(self, **kw):
            raise ValueError("tidak didukung")

    cli.amankan_stream(Rewel())  # tidak boleh melempar


def test_pesan_dengan_emoji_dan_bullet_dapat_dilog(tmp_path, capsys):
    import logging

    cli.setup_logging(tmp_path / "logs", verbose=False)
    logging.getLogger("ihsg_screener").info("alert \U0001F680 dengan \u2022 bullet")

    berkas = (tmp_path / "logs" / "scanner.log").read_text(encoding="utf-8")
    assert "\U0001F680" in berkas
    assert "\u2022" in berkas
