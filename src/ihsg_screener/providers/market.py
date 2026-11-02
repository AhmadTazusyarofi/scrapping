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
