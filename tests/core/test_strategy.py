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
