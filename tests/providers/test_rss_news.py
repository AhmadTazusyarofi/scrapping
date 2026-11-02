from datetime import datetime, timedelta, timezone

import pytest

from ihsg_screener.config import HttpConfig
from ihsg_screener.models import Ticker
from ihsg_screener.providers import rss_news

BBRI = Ticker(symbol="BBRI.JK", name="Bank Rakyat Indonesia", aliases=("BBRI", "BRI"))
ANTM = Ticker(symbol="ANTM.JK", name="Aneka Tambang", aliases=("ANTM", "Antam"))
HTTP_CFG = HttpConfig(timeout_seconds=15, retries=1, backoff_base_seconds=0)


def _rfc822(dt: datetime) -> str:
    return dt.strftime("%a, %d %b %Y %H:%M:%S %z")


def _feed(*items: tuple[str, str, str]) -> bytes:
    isi = "".join(
        f"<item><title>{j}</title><description>{d}</description>"
        f"<link>{u}</link><pubDate>{_rfc822(datetime.now(timezone.utc))}</pubDate></item>"
        for j, d, u in items
    )
    return (
        "<?xml version='1.0' encoding='UTF-8'?><rss version='2.0'><channel>"
        f"<title>Uji</title>{isi}</channel></rss>"
    ).encode("utf-8")


def _feed_bertanggal(judul: str, umur_jam: int) -> bytes:
    saat = datetime.now(timezone.utc) - timedelta(hours=umur_jam)
    return (
        "<?xml version='1.0' encoding='UTF-8'?><rss version='2.0'><channel><item>"
        f"<title>{judul}</title><description>d</description>"
        f"<link>https://x.id/1</link><pubDate>{_rfc822(saat)}</pubDate>"
        "</item></channel></rss>"
    ).encode("utf-8")


class FakeResponse:
    def __init__(self, content=b"", status_code=200):
        self.content = content
        self.status_code = status_code


class FakeSession:
    def __init__(self, per_url):
        self.per_url = per_url
        self.calls = []

    def get(self, url, timeout=None, headers=None):
        self.calls.append({"url": url, "timeout": timeout})
        hasil = self.per_url[url]
        if isinstance(hasil, Exception):
            raise hasil
        return hasil


def test_mengurai_item_menjadi_article():
    session = FakeSession({
        "https://a.id/rss": FakeResponse(_feed(
            ("BBRI cetak laba", "Naik 12 persen", "https://a.id/1"),
        )),
    })
    p = rss_news.RssNewsProvider(["https://a.id/rss"], HTTP_CFG, session=session)

    hasil = p.fetch(BBRI)

    assert len(hasil) == 1
    assert hasil[0].title == "BBRI cetak laba"
    assert hasil[0].description == "Naik 12 persen"
    assert hasil[0].url == "https://a.id/1"
    assert hasil[0].source == "a.id"


def test_feed_hanya_diambil_sekali_untuk_banyak_emiten():
    """Inti keunggulan RSS: biayanya per feed, bukan per emiten."""
    session = FakeSession({
        "https://a.id/rss": FakeResponse(_feed(
            ("BBRI cetak laba", "d", "https://a.id/1"),
            ("Antam naikkan produksi", "d", "https://a.id/2"),
        )),
    })
    p = rss_news.RssNewsProvider(["https://a.id/rss"], HTTP_CFG, session=session)

    p.fetch(BBRI)
    p.fetch(ANTM)
    p.fetch(BBRI)

    assert len(session.calls) == 1


def test_menyaring_per_emiten():
    session = FakeSession({
        "https://a.id/rss": FakeResponse(_feed(
            ("BBRI cetak laba", "d", "https://a.id/1"),
            ("Antam naikkan produksi emas", "d", "https://a.id/2"),
            ("Cuaca panas di Jakarta", "d", "https://a.id/3"),
        )),
    })
    p = rss_news.RssNewsProvider(["https://a.id/rss"], HTTP_CFG, session=session)

    assert [a.title for a in p.fetch(BBRI)] == ["BBRI cetak laba"]
    assert [a.title for a in p.fetch(ANTM)] == ["Antam naikkan produksi emas"]


def test_menggabungkan_beberapa_feed():
    session = FakeSession({
        "https://a.id/rss": FakeResponse(_feed(("BBRI naik", "d", "https://a.id/1"))),
        "https://b.id/rss": FakeResponse(_feed(("BBRI turun", "d", "https://b.id/1"))),
    })
    p = rss_news.RssNewsProvider(
        ["https://a.id/rss", "https://b.id/rss"], HTTP_CFG, session=session
    )

    assert len(p.fetch(BBRI)) == 2


def test_feed_rusak_tidak_menjatuhkan_feed_lain():
    session = FakeSession({
        "https://rusak.id/rss": FakeResponse(b"<html>bukan xml sama sekali"),
        "https://b.id/rss": FakeResponse(_feed(("BBRI naik", "d", "https://b.id/1"))),
    })
    p = rss_news.RssNewsProvider(
        ["https://rusak.id/rss", "https://b.id/rss"], HTTP_CFG, session=session
    )

    assert [a.title for a in p.fetch(BBRI)] == ["BBRI naik"]


def test_feed_yang_melempar_exception_tidak_menjatuhkan_run():
    session = FakeSession({
        "https://mati.id/rss": OSError("koneksi ditolak"),
        "https://b.id/rss": FakeResponse(_feed(("BBRI naik", "d", "https://b.id/1"))),
    })
    p = rss_news.RssNewsProvider(
        ["https://mati.id/rss", "https://b.id/rss"], HTTP_CFG, session=session
    )

    assert [a.title for a in p.fetch(BBRI)] == ["BBRI naik"]


def test_feed_dengan_status_bukan_200_dilewati():
    session = FakeSession({
        "https://tolak.id/rss": FakeResponse(b"", status_code=403),
        "https://b.id/rss": FakeResponse(_feed(("BBRI naik", "d", "https://b.id/1"))),
    })
    p = rss_news.RssNewsProvider(
        ["https://tolak.id/rss", "https://b.id/rss"], HTTP_CFG, session=session
    )

    assert [a.title for a in p.fetch(BBRI)] == ["BBRI naik"]


def test_artikel_terlalu_lama_dibuang():
    session = FakeSession({
        "https://a.id/rss": FakeResponse(_feed_bertanggal("BBRI kabar lama", umur_jam=200)),
    })
    p = rss_news.RssNewsProvider(
        ["https://a.id/rss"], HTTP_CFG, session=session, max_age_hours=72
    )

    assert p.fetch(BBRI) == []


def test_artikel_masih_baru_dipertahankan():
    session = FakeSession({
        "https://a.id/rss": FakeResponse(_feed_bertanggal("BBRI kabar baru", umur_jam=5)),
    })
    p = rss_news.RssNewsProvider(
        ["https://a.id/rss"], HTTP_CFG, session=session, max_age_hours=72
    )

    assert len(p.fetch(BBRI)) == 1


def test_selalu_menetapkan_timeout():
    session = FakeSession({"https://a.id/rss": FakeResponse(_feed(("BBRI", "d", "u")))})
    p = rss_news.RssNewsProvider(["https://a.id/rss"], HTTP_CFG, session=session)

    p.fetch(BBRI)

    assert session.calls[0]["timeout"] == 15


def test_seluruh_feed_gagal_menghasilkan_daftar_kosong_bukan_exception():
    session = FakeSession({"https://mati.id/rss": OSError("putus")})
    p = rss_news.RssNewsProvider(["https://mati.id/rss"], HTTP_CFG, session=session)

    assert p.fetch(BBRI) == []


def test_parse_rfc822_menangani_format_umum():
    assert rss_news.parse_pubdate("Tue, 25 Aug 2026 12:33:56 +0700") is not None
    assert rss_news.parse_pubdate("Tue, 25 Aug 2026 12:33:56 GMT") is not None
    assert rss_news.parse_pubdate("bukan tanggal") is None
    assert rss_news.parse_pubdate("") is None


def test_item_tanpa_pubdate_tetap_dipertahankan():
    xml = (
        "<?xml version='1.0' encoding='UTF-8'?><rss version='2.0'><channel><item>"
        "<title>BBRI tanpa tanggal</title><description>d</description>"
        "<link>https://a.id/1</link></item></channel></rss>"
    ).encode("utf-8")
    session = FakeSession({"https://a.id/rss": FakeResponse(xml)})
    p = rss_news.RssNewsProvider(["https://a.id/rss"], HTTP_CFG, session=session)

    assert len(p.fetch(BBRI)) == 1


def test_deskripsi_html_dibersihkan_dari_tag():
    session = FakeSession({
        "https://a.id/rss": FakeResponse(_feed(
            ("BBRI cetak laba", "&lt;p&gt;Naik 12 persen&lt;/p&gt;", "https://a.id/1"),
        )),
    })
    p = rss_news.RssNewsProvider(["https://a.id/rss"], HTTP_CFG, session=session)

    assert p.fetch(BBRI)[0].description == "Naik 12 persen"
