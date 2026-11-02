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
from .providers.rss_news import RssNewsProvider
from .providers.sentiment_engine import SentimentEngine
from .runlock import AlreadyRunningError, RunLock
from .storage.repository import Repository

logger = logging.getLogger("ihsg_screener")

EXIT_OK = 0
EXIT_DEGRADED = 1
EXIT_FATAL = 2

# Pustaka ini bicara sangat banyak pada level DEBUG. Membiarkannya ikut naik
# saat --verbose membuat flag itu justru tidak berguna untuk mendiagnosis:
# log aplikasi tenggelam di antara ribuan baris lalu lintas HTTP.
PUSTAKA_BISING = (
    "httpcore",
    "httpx",
    "urllib3",
    "transformers",
    "yfinance",
    "peewee",
    "filelock",
    "matplotlib",
)


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


def amankan_stream(stream) -> None:
    """Pastikan stream dapat menampung karakter non-ASCII.

    Pesan alert memuat emoji dan bullet, sementara konsol Windows bawaannya
    cp1252. Tanpa ini, logging gagal meng-encode dan membuang pesannya diam-diam
    — tepat pesan yang paling ingin dilihat saat --dry-run.
    """
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass


def setup_logging(log_dir: str | Path, verbose: bool) -> None:
    path = Path(log_dir)
    path.mkdir(parents=True, exist_ok=True)
    amankan_stream(sys.stdout)

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

    for nama in PUSTAKA_BISING:
        logging.getLogger(nama).setLevel(logging.WARNING)


def render_results(results) -> str:
    """Susun tabel keputusan per emiten.

    Tanpa ini, '--dry-run' hanya melaporkan jumlah kandidat dan alert, sehingga
    tidak menjawab pertanyaan yang justru menjadi alasan flag itu ada: sinyal
    apa yang akan keluar, dan mengapa yang lain tidak.
    """
    if not results:
        return "(tidak ada hasil)"

    urutan = {
        "BUY_ALERT": 0,
        "REJECTED_SENTIMENT": 1,
        "SKIPPED_NO_NEWS": 2,
        "SKIPPED_DUPLICATE": 3,
        "ERROR": 4,
        "REJECTED_TECHNICAL": 5,
        "SKIPPED_NO_DATA": 6,
    }
    baris = [
        f"{'EMITEN':<10} {'CLOSE':>10}  {'KEPUTUSAN':<20} ALASAN",
        "-" * 88,
    ]
    for r in sorted(results, key=lambda x: (urutan.get(x.decision.value, 9), x.symbol)):
        close = f"{r.technical.close:,.0f}" if r.technical else "-"
        baris.append(f"{r.symbol:<10} {close:>10}  {r.decision.value:<20} {r.reason}")
    return "\n".join(baris)


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


def build_news_provider(settings):
    """Pilih sumber berita sesuai `news.source`.

    Keduanya memakai antarmuka `fetch(ticker)` yang sama, sehingga pipeline
    tidak perlu tahu sumber mana yang sedang dipakai.
    """
    if settings.news.source == "rss":
        return RssNewsProvider(
            settings.news.feeds,
            settings.http,
            max_age_hours=settings.news.max_age_hours,
        )
    return NewsProvider(settings.secrets.newsapi_key, settings.news, settings.http)


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
                news=build_news_provider(settings),
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
    print()
    print(render_results(summary.results))
    return exit_code_for(summary.status)


if __name__ == "__main__":
    raise SystemExit(main())
