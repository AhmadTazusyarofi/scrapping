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
