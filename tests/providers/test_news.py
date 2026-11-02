import pytest

from ihsg_screener.config import HttpConfig, NewsConfig
from ihsg_screener.errors import QuotaExceededError
from ihsg_screener.models import Ticker
from ihsg_screener.providers import news

BBRI = Ticker(symbol="BBRI.JK", name="Bank Rakyat Indonesia", aliases=("BBRI", "BRI"))
NEWS_CFG = NewsConfig(page_size=3, max_requests_per_run=2, lookback_days=3, language="id")
HTTP_CFG = HttpConfig(timeout_seconds=15, retries=1, backoff_base_seconds=0)


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {"status": "ok", "articles": []}

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        return self._responses.pop(0) if self._responses else FakeResponse()


def _payload(*judul):
    return {
        "status": "ok",
        "articles": [
            {
                "title": j,
                "description": f"deskripsi {j}",
                "url": f"https://contoh.id/{i}",
                "source": {"name": "Detikcom"},
                "publishedAt": "2026-08-25T10:00:00Z",
            }
            for i, j in enumerate(judul)
        ],
    }


def test_build_query_menggabungkan_nama_dan_alias():
    query = news.build_query(BBRI)

    assert '"Bank Rakyat Indonesia"' in query
    assert "BBRI" in query
    assert " OR " in query


def test_fetch_mengurai_artikel():
    session = FakeSession(FakeResponse(payload=_payload("BBRI cetak laba")))
    provider = news.NewsProvider("kunci", NEWS_CFG, HTTP_CFG, session=session)

    articles = provider.fetch(BBRI)

    assert len(articles) == 1
    assert articles[0].title == "BBRI cetak laba"
    assert articles[0].source == "Detikcom"
    assert articles[0].url == "https://contoh.id/0"


def test_fetch_selalu_menetapkan_timeout():
    session = FakeSession(FakeResponse(payload=_payload("a")))
    provider = news.NewsProvider("kunci", NEWS_CFG, HTTP_CFG, session=session)

    provider.fetch(BBRI)

    assert session.calls[0]["timeout"] == 15


def test_fetch_mengirim_filter_bahasa_dan_page_size():
    session = FakeSession(FakeResponse(payload=_payload("a")))
    provider = news.NewsProvider("kunci", NEWS_CFG, HTTP_CFG, session=session)

    provider.fetch(BBRI)
    params = session.calls[0]["params"]

    assert params["language"] == "id"
    assert params["pageSize"] == 3
    assert params["sortBy"] == "publishedAt"


def test_fetch_tidak_pernah_menaruh_api_key_di_url():
    session = FakeSession(FakeResponse(payload=_payload("a")))
    provider = news.NewsProvider("rahasia", NEWS_CFG, HTTP_CFG, session=session)

    provider.fetch(BBRI)

    assert "rahasia" not in session.calls[0]["url"]
    assert "rahasia" not in str(session.calls[0]["params"])


def test_fetch_menangani_deskripsi_null():
    payload = _payload("a")
    payload["articles"][0]["description"] = None
    session = FakeSession(FakeResponse(payload=payload))
    provider = news.NewsProvider("kunci", NEWS_CFG, HTTP_CFG, session=session)

    assert provider.fetch(BBRI)[0].description == ""


def test_requests_used_bertambah_tiap_panggilan():
    session = FakeSession(FakeResponse(payload=_payload("a")), FakeResponse(payload=_payload("b")))
    provider = news.NewsProvider("kunci", NEWS_CFG, HTTP_CFG, session=session)

    provider.fetch(BBRI)
    provider.fetch(BBRI)

    assert provider.requests_used == 2


def test_budget_habis_melempar_tanpa_memanggil_jaringan():
    session = FakeSession(FakeResponse(payload=_payload("a")), FakeResponse(payload=_payload("b")))
    provider = news.NewsProvider("kunci", NEWS_CFG, HTTP_CFG, session=session)
    provider.fetch(BBRI)
    provider.fetch(BBRI)

    with pytest.raises(QuotaExceededError, match="budget"):
        provider.fetch(BBRI)

    assert len(session.calls) == 2


def test_http_429_dinaikkan_menjadi_quota_exceeded():
    session = FakeSession(FakeResponse(status_code=429, payload={"message": "limit"}))
    provider = news.NewsProvider("kunci", NEWS_CFG, HTTP_CFG, session=session)

    with pytest.raises(QuotaExceededError):
        provider.fetch(BBRI)


def test_status_error_dari_newsapi_menghasilkan_daftar_kosong():
    session = FakeSession(FakeResponse(payload={"status": "error", "message": "buruk"}))
    provider = news.NewsProvider("kunci", NEWS_CFG, HTTP_CFG, session=session)

    assert provider.fetch(BBRI) == []
