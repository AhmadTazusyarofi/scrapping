import pytest
import yaml

from ihsg_screener.config import load_watchlist
from ihsg_screener.errors import ConfigError


def _write(tmp_path, data):
    path = tmp_path / "watchlist.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_load_watchlist_mengurai_ticker(tmp_path):
    path = _write(tmp_path, {"tickers": [
        {"symbol": "BBRI.JK", "name": "Bank Rakyat Indonesia", "aliases": ["BBRI", "BRI"]},
        {"symbol": "TLKM.JK", "name": "Telkom Indonesia"},
    ]})

    tickers = load_watchlist(path)

    assert [t.symbol for t in tickers] == ["BBRI.JK", "TLKM.JK"]
    assert tickers[0].aliases == ("BBRI", "BRI")
    assert tickers[1].aliases == ()
    assert tickers[0].code == "BBRI"


def test_load_watchlist_menolak_daftar_kosong(tmp_path):
    with pytest.raises(ConfigError, match="kosong"):
        load_watchlist(_write(tmp_path, {"tickers": []}))


def test_load_watchlist_menolak_ticker_tanpa_nama(tmp_path):
    path = _write(tmp_path, {"tickers": [{"symbol": "BBRI.JK"}]})

    with pytest.raises(ConfigError, match="name"):
        load_watchlist(path)


def test_load_watchlist_menolak_simbol_duplikat(tmp_path):
    path = _write(tmp_path, {"tickers": [
        {"symbol": "BBRI.JK", "name": "A"},
        {"symbol": "BBRI.JK", "name": "B"},
    ]})

    with pytest.raises(ConfigError, match="duplikat"):
        load_watchlist(path)
