"""Pengiriman alert ke Telegram Bot API."""

from __future__ import annotations

import html
import logging

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..config import HttpConfig
from ..errors import NotifierError
from ..models import SentimentVerdict, TechnicalSignal, Ticker

logger = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"


def _esc(nilai) -> str:
    """Escape untuk parse_mode HTML Telegram."""
    return html.escape(str(nilai), quote=False)


def format_alert(
    ticker: Ticker, signal: TechnicalSignal, verdict: SentimentVerdict
) -> str:
    """Susun pesan alert. Fungsi murni sehingga isinya dapat diuji langsung.

    Memakai HTML, bukan Markdown. Nama indikator dan aturan mengandung
    underscore ('sma_cross', 'sma_fast'), yang di Markdown Telegram adalah
    penanda italic: jumlah ganjil membuat parser gagal menemukan penutupnya
    dan menolak SELURUH pesan dengan 400. Di HTML underscore tidak bermakna,
    dan karakter yang bermakna hanya tiga dan tegas aturan escape-nya.
    """
    indikator = "\n".join(
        f"  • {_esc(nama)}: {nilai:,.2f}"
        for nama, nilai in sorted(signal.indicators.items())
    )
    tautan = "\n".join(
        f"  • [{item.label.value} {item.score:.2f}] {_esc(item.article.url)}"
        for item in verdict.per_article
    )

    baris = [
        "🚀 <b>BUY ALERT</b>",
        "",
        f"<b>{_esc(ticker.symbol)}</b> — {_esc(ticker.name)}",
        f"Tanggal data: {signal.as_of.isoformat()}",
        f"Harga penutupan: {signal.close:,.2f}",
        "",
        f"<b>Teknikal:</b> BULLISH ({_esc(', '.join(signal.passed_rules))})",
        indikator,
        "",
        f"<b>Sentimen:</b> {verdict.label.value} "
        f"(skor {verdict.score:.2f}, {verdict.analyzed_count} artikel)",
        tautan,
    ]
    return "\n".join(b for b in baris if b is not None)


class TelegramNotifier:
    """Mengirim pesan ke satu Chat ID lewat Telegram Bot API."""

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        http_config: HttpConfig,
        session=None,
    ) -> None:
        self._token = bot_token
        self._chat_id = chat_id
        self._http = http_config
        self._session = session or self._default_session()

    @staticmethod
    def _default_session():
        import requests

        return requests.Session()

    def send(self, text: str) -> None:
        """Kirim pesan. Melempar NotifierError bila Telegram tidak membalas 200."""
        url = f"{API_BASE}/bot{self._token}/sendMessage"
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        @retry(
            stop=stop_after_attempt(self._http.retries),
            wait=wait_exponential(multiplier=self._http.backoff_base_seconds),
            retry=retry_if_exception_type(OSError),
            reraise=True,
        )
        def _call():
            return self._session.post(url, json=payload, timeout=self._http.timeout_seconds)

        response = _call()
        if response.status_code != 200:
            # Token tidak pernah disertakan dalam pesan error agar tidak bocor ke log.
            raise NotifierError(
                f"Telegram membalas {response.status_code}: {response.text[:200]}"
            )
