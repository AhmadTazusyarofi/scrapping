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
