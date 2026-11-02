from datetime import date

import pytest

from ihsg_screener.config import HttpConfig
from ihsg_screener.errors import NotifierError
from ihsg_screener.models import (
    Article,
    ArticleSentiment,
    SentimentLabel,
    SentimentVerdict,
    TechnicalSignal,
    Ticker,
)
from ihsg_screener.notifiers import telegram

HTTP_CFG = HttpConfig(timeout_seconds=15, retries=1, backoff_base_seconds=0)
BBRI = Ticker(symbol="BBRI.JK", name="Bank Rakyat Indonesia", aliases=("BBRI",))


def _signal():
    return TechnicalSignal(
        symbol="BBRI.JK",
        is_bullish=True,
        close=5000.0,
        as_of=date(2026, 8, 25),
        indicators={"sma_fast": 5010.5, "sma_slow": 4900.25},
        passed_rules=("sma_cross",),
        failed_rules=(),
    )


def _verdict():
    artikel = Article(
        title="BBRI cetak laba", description="", url="https://contoh.id/1",
        source="Detikcom", published_at="2026-08-25T10:00:00Z",
    )
    return SentimentVerdict(
        label=SentimentLabel.POSITIF,
        score=0.85,
        analyzed_count=2,
        rejected_count=1,
        per_article=(ArticleSentiment(article=artikel, label=SentimentLabel.POSITIF, score=0.9),),
    )


class FakeResponse:
    def __init__(self, status_code=200, text="ok"):
        self.status_code = status_code
        self.text = text


class FakeSession:
    def __init__(self, response=None):
        self.response = response or FakeResponse()
        self.calls = []

    def post(self, url, json=None, timeout=None):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        return self.response


def test_format_alert_memuat_simbol_dan_harga():
    pesan = telegram.format_alert(BBRI, _signal(), _verdict())

    assert "BBRI.JK" in pesan
    assert "5,000.00" in pesan
    assert "BUY ALERT" in pesan


def test_format_alert_memuat_nama_perusahaan_dan_tanggal():
    pesan = telegram.format_alert(BBRI, _signal(), _verdict())

    assert "Bank Rakyat Indonesia" in pesan
    assert "2026-08-25" in pesan


def test_format_alert_memuat_aturan_yang_lulus_dan_nilainya():
    pesan = telegram.format_alert(BBRI, _signal(), _verdict())

    assert "sma_cross" in pesan
    assert "sma_fast" in pesan


def test_format_alert_memuat_ringkasan_sentimen():
    pesan = telegram.format_alert(BBRI, _signal(), _verdict())

    assert "POSITIF" in pesan
    assert "0.85" in pesan
    assert "2" in pesan


def test_format_alert_memuat_tautan_artikel():
    pesan = telegram.format_alert(BBRI, _signal(), _verdict())

    assert "https://contoh.id/1" in pesan


def test_send_memanggil_endpoint_sendmessage_dengan_timeout():
    session = FakeSession()
    notifier = telegram.TelegramNotifier("token123", "chat456", HTTP_CFG, session=session)

    notifier.send("halo")

    assert session.calls[0]["url"] == "https://api.telegram.org/bottoken123/sendMessage"
    assert session.calls[0]["json"]["chat_id"] == "chat456"
    assert session.calls[0]["json"]["text"] == "halo"
    assert session.calls[0]["timeout"] == 15


def test_send_melempar_notifier_error_pada_status_bukan_200():
    session = FakeSession(FakeResponse(status_code=400, text="bad request"))
    notifier = telegram.TelegramNotifier("token123", "chat456", HTTP_CFG, session=session)

    with pytest.raises(NotifierError, match="400"):
        notifier.send("halo")


def test_send_tidak_membocorkan_token_di_pesan_error():
    session = FakeSession(FakeResponse(status_code=401, text="unauthorized"))
    notifier = telegram.TelegramNotifier("token-rahasia", "chat456", HTTP_CFG, session=session)

    with pytest.raises(NotifierError) as exc:
        notifier.send("halo")

    assert "token-rahasia" not in str(exc.value)


def test_format_alert_tidak_merusak_parser_karena_underscore():
    """Regresi: 'sma_cross'/'sma_fast' membuat Telegram menolak pesan dengan
    parse_mode Markdown ('can't find end of the entity'). Mode HTML tidak
    memperlakukan underscore sebagai penanda, jadi harus lolos apa adanya."""
    pesan = telegram.format_alert(BBRI, _signal(), _verdict())

    assert "sma_cross" in pesan
    assert "sma_fast" in pesan
    assert "sma_slow" in pesan


def test_format_alert_meng_escape_karakter_khusus_html():
    ticker = Ticker(symbol="XYZ.JK", name="Astra & <Sons>", aliases=())

    pesan = telegram.format_alert(ticker, _signal(), _verdict())

    assert "Astra &amp; &lt;Sons&gt;" in pesan
    assert "<Sons>" not in pesan


def test_format_alert_memakai_tag_html_bukan_markdown():
    pesan = telegram.format_alert(BBRI, _signal(), _verdict())

    assert "<b>" in pesan
    assert "*BUY ALERT*" not in pesan


def test_send_memakai_parse_mode_html():
    session = FakeSession()
    notifier = telegram.TelegramNotifier("token123", "chat456", HTTP_CFG, session=session)

    notifier.send("halo")

    assert session.calls[0]["json"]["parse_mode"] == "HTML"
