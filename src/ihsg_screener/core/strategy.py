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
