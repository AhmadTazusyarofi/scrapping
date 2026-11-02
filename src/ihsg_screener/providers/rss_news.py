"""Sumber berita dari RSS media finansial Indonesia.

Berbeda dari NewsAPI yang menagih satu permintaan per emiten, feed diambil
sekali per run lalu disaring per emiten dari kumpulan yang sama. Biayanya
karena itu sebanding dengan jumlah feed, bukan jumlah emiten: watchlist 5 atau
45 emiten sama-sama memerlukan segelintir permintaan HTTP, tanpa kuota harian.

Antarmukanya sengaja dibuat identik dengan NewsProvider (`fetch(ticker)`),
sehingga pipeline tidak perlu tahu sumber berita mana yang sedang dipakai.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Sequence
from urllib.parse import urlparse

from ..config import HttpConfig
from ..core.textproc import clean_text, is_relevant
from ..models import Article, Ticker

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; IHSGScreener/0.1)"
DEFAULT_MAX_AGE_HOURS = 72


def parse_pubdate(nilai: str) -> datetime | None:
    """Urai tanggal RFC-822 milik RSS. None bila tidak dapat diurai."""
    if not nilai:
        return None
    try:
        saat = parsedate_to_datetime(nilai)
    except (TypeError, ValueError):
        return None
    if saat is None:
        return None
    return saat if saat.tzinfo else saat.replace(tzinfo=timezone.utc)


class RssNewsProvider:
    """Mengumpulkan artikel dari beberapa feed RSS, lalu menyaring per emiten."""

    def __init__(
        self,
        feeds: Sequence[str],
        http_config: HttpConfig,
        session=None,
        max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
    ) -> None:
        self.feeds = list(feeds)
        self._http = http_config
        self._session = session or self._default_session()
        self._max_age_hours = max_age_hours
        self._cache: list[Article] | None = None

    @staticmethod
    def _default_session():
        import requests

        s = requests.Session()
        s.headers.update({"User-Agent": USER_AGENT})
        return s

    @property
    def requests_used(self) -> int:
        """Jumlah permintaan yang sudah dipakai; nol sebelum feed diambil."""
        return 0 if self._cache is None else len(self.feeds)

    def fetch(self, ticker: Ticker) -> list[Article]:
        """Artikel yang relevan bagi satu emiten, dari kumpulan feed."""
        if self._cache is None:
            self._cache = self._collect()
        return [a for a in self._cache if is_relevant(a, ticker)]

    def _collect(self) -> list[Article]:
        batas = datetime.now(timezone.utc) - timedelta(hours=self._max_age_hours)
        artikel: list[Article] = []

        for url in self.feeds:
            # Satu feed yang mati tidak boleh menjatuhkan sumber berita lainnya.
            try:
                response = self._session.get(
                    url, timeout=self._http.timeout_seconds,
                    headers={"User-Agent": USER_AGENT},
                )
            except Exception as exc:
                logger.warning("Feed %s tidak dapat diambil: %s", url, exc)
                continue

            if getattr(response, "status_code", 200) != 200:
                logger.warning("Feed %s membalas %s", url, response.status_code)
                continue

            try:
                root = ET.fromstring(response.content)
            except ET.ParseError as exc:
                logger.warning("Feed %s bukan XML yang sah: %s", url, exc)
                continue

            sumber = urlparse(url).netloc.replace("www.", "")
            for item in root.findall(".//item"):
                terurai = self._to_article(item, sumber)
                if terurai is None:
                    continue
                a, saat = terurai
                # Item tanpa pubDate dipertahankan: lebih baik menilai artikel
                # yang mungkin lama daripada membuang yang mungkin baru.
                if saat is not None and saat < batas:
                    continue
                artikel.append(a)

        logger.info(
            "Terkumpul %d artikel dari %d feed", len(artikel), len(self.feeds)
        )
        return artikel

    @staticmethod
    def _to_article(item, sumber: str) -> tuple[Article, datetime | None] | None:
        judul = clean_text(item.findtext("title") or "")
        if not judul:
            return None
        return (
            Article(
                title=judul,
                description=clean_text(item.findtext("description") or ""),
                url=(item.findtext("link") or "").strip(),
                source=sumber,
                published_at=(item.findtext("pubDate") or "").strip(),
            ),
            parse_pubdate(item.findtext("pubDate") or ""),
        )
