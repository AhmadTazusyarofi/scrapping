import pytest
import yaml

from ihsg_screener.config import load_settings
from ihsg_screener.errors import ConfigError

FULL_ENV = {
    "NEWSAPI_KEY": "k",
    "TELEGRAM_BOT_TOKEN": "t",
    "TELEGRAM_CHAT_ID": "c",
}


def _write(tmp_path, data):
    path = tmp_path / "settings.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def _valid_data():
    return {
        "technical": {"min_bars": 60, "lookback_days": 180, "rules": {"sma_cross": {"enabled": True, "fast": 5, "slow": 20}}},
        "sentiment": {"model": "m", "articles_per_ticker": 3, "min_articles": 1,
                      "min_avg_score": 0.6, "neutral_weight": 0.0,
                      "veto_on_strong_negative": True, "strong_negative_threshold": 0.8,
                      "batch_size": 8},
        "news": {"page_size": 3, "max_requests_per_run": 40, "lookback_days": 3, "language": "id"},
        "alerts": {"cooldown_days": 5},
        "http": {"timeout_seconds": 15, "retries": 3, "backoff_base_seconds": 2},
        "runtime": {"db_path": "data/scanner.db", "log_dir": "logs",
                    "lock_file": "data/scanner.lock", "max_data_age_days": 4},
    }


def test_load_settings_membaca_seluruh_bagian(tmp_path):
    settings = load_settings(_write(tmp_path, _valid_data()), FULL_ENV)

    assert settings.news.max_requests_per_run == 40
    assert settings.alerts.cooldown_days == 5
    assert settings.http.timeout_seconds == 15
    assert settings.sentiment.min_avg_score == 0.6
    assert settings.technical["rules"]["sma_cross"]["fast"] == 5
    assert settings.secrets.telegram_chat_id == "c"


def test_load_settings_menolak_rahasia_yang_kosong(tmp_path):
    path = _write(tmp_path, _valid_data())
    env = dict(FULL_ENV, TELEGRAM_BOT_TOKEN="")

    with pytest.raises(ConfigError, match="TELEGRAM_BOT_TOKEN"):
        load_settings(path, env)


def test_load_settings_menolak_bagian_yang_hilang(tmp_path):
    data = _valid_data()
    del data["news"]

    with pytest.raises(ConfigError, match="news"):
        load_settings(_write(tmp_path, data), FULL_ENV)


def test_load_settings_menolak_file_yang_tidak_ada(tmp_path):
    with pytest.raises(ConfigError, match="tidak ditemukan"):
        load_settings(tmp_path / "hilang.yaml", FULL_ENV)


def test_kunci_news_baru_punya_default_sehingga_config_lama_tetap_jalan(tmp_path):
    """settings.yaml yang ditulis sebelum RSS ada tidak boleh tiba-tiba fatal."""
    settings = load_settings(_write(tmp_path, _valid_data()), FULL_ENV)

    assert settings.news.source == "newsapi"
    assert settings.news.feeds == ()


def test_membaca_konfigurasi_sumber_rss(tmp_path):
    data = _valid_data()
    data["news"].update({
        "source": "rss",
        "feeds": ["https://a.id/rss", "https://b.id/rss"],
        "max_age_hours": 48,
    })

    settings = load_settings(_write(tmp_path, data), FULL_ENV)

    assert settings.news.source == "rss"
    assert settings.news.feeds == ("https://a.id/rss", "https://b.id/rss")
    assert settings.news.max_age_hours == 48


def test_menolak_sumber_berita_yang_tidak_dikenal(tmp_path):
    data = _valid_data()
    data["news"]["source"] = "koran-bekas"

    with pytest.raises(ConfigError, match="koran-bekas"):
        load_settings(_write(tmp_path, data), FULL_ENV)


def test_menolak_sumber_rss_tanpa_daftar_feed(tmp_path):
    data = _valid_data()
    data["news"]["source"] = "rss"

    with pytest.raises(ConfigError, match="feeds"):
        load_settings(_write(tmp_path, data), FULL_ENV)
