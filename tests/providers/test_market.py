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
