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
