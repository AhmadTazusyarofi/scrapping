"""Klien NewsAPI dengan budget kuota lokal dan retry transien."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..config import HttpConfig, NewsConfig
from ..errors import QuotaExceededError
from ..models import Article, Ticker

logger = logging.getLogger(__name__)

ENDPOINT = "https://newsapi.org/v2/everything"


def build_query(ticker: Ticker) -> str:
    """Bangun query dari nama perusahaan dan alias.

    Pencarian hanya dengan kode emiten memberi recall buruk untuk berita
    Indonesia, sehingga nama perusahaan selalu disertakan.
    """
    terms = [f'"{ticker.name}"']
    for alias in (ticker.code, *ticker.aliases):
        if alias and alias not in terms:
            terms.append(alias)
    return " OR ".join(dict.fromkeys(terms))


class NewsProvider:
    """Mengambil berita berbahasa Indonesia per emiten."""

    def __init__(
        self,
        api_key: str,
        news_config: NewsConfig,
        http_config: HttpConfig,
        session=None,
    ) -> None:
        self._api_key = api_key
        self._news = news_config
        self._http = http_config
        self._session = session or self._default_session()
        self._requests_used = 0
        # API key dikirim lewat header, tidak pernah lewat URL atau query, agar
        # tidak bocor ke log akses server maupun log aplikasi.
        if hasattr(self._session, "headers"):
            self._session.headers.update({"X-Api-Key": api_key})

    @staticmethod
    def _default_session():
        import requests

        return requests.Session()

    @property
    def requests_used(self) -> int:
        return self._requests_used

    def fetch(self, ticker: Ticker) -> list[Article]:
        """Ambil artikel terbaru untuk satu emiten.

        Melempar QuotaExceededError bila budget lokal habis, tanpa menyentuh
        jaringan, sehingga sistem berhenti pada batas yang kita tetapkan
        sendiri alih-alih pada penolakan NewsAPI di tengah jalan.
        """
        if self._requests_used >= self._news.max_requests_per_run:
            raise QuotaExceededError(
                f"budget permintaan NewsAPI habis "
                f"({self._news.max_requests_per_run} per run)"
            )

        params = {
            "q": build_query(ticker),
            "language": self._news.language,
            "sortBy": "publishedAt",
            "pageSize": self._news.page_size,
            "from": (date.today() - timedelta(days=self._news.lookback_days)).isoformat(),
        }

        self._requests_used += 1
        response = self._get(params)

        if response.status_code == 429:
            raise QuotaExceededError("NewsAPI membalas 429: batas permintaan tercapai")
        if response.status_code != 200:
            logger.warning(
                "NewsAPI membalas %s untuk %s", response.status_code, ticker.symbol
            )
            return []

        payload = response.json()
        if payload.get("status") != "ok":
            logger.warning(
                "NewsAPI status=%s untuk %s: %s",
                payload.get("status"),
                ticker.symbol,
                payload.get("message"),
            )
            return []

        return [self._to_article(raw) for raw in payload.get("articles", [])]

    def _get(self, params: dict):
        @retry(
            stop=stop_after_attempt(self._http.retries),
            wait=wait_exponential(multiplier=self._http.backoff_base_seconds),
            retry=retry_if_exception_type(OSError),
            reraise=True,
        )
        def _call():
            return self._session.get(
                ENDPOINT,
                params=params,
                timeout=self._http.timeout_seconds,
            )

        return _call()

    @staticmethod
    def _to_article(raw: dict) -> Article:
        source = raw.get("source") or {}
        return Article(
            title=raw.get("title") or "",
            description=raw.get("description") or "",
            url=raw.get("url") or "",
            source=source.get("name") or "",
            published_at=raw.get("publishedAt") or "",
        )
