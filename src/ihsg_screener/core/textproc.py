"""Pembersihan teks berita dan filter relevansi sebelum inferensi.

Pemotongan 512 token dikerjakan tokenizer di providers/sentiment_engine.py,
bukan di sini. Modul ini murni: tanpa I/O dan tanpa dependensi eksternal.
"""

from __future__ import annotations

import html
import re
from typing import Sequence

from ..models import Article, Ticker

_TAG = re.compile(r"<[^>]+>")
_URL = re.compile(r"https?://\S+|www\.\S+")
_TRUNCATION = re.compile(r"[…\.]*\s*\[\+\s*\d+\s*chars?\]", re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")
_REMOVED = "[removed]"

# Kode emiten IDX selalu empat huruf kapital. Pencocokan sengaja peka huruf
# besar-kecil: judul berita ditulis Title Case, sehingga token empat huruf yang
# seluruhnya kapital hampir selalu kode emiten atau akronim.
_KODE_EMITEN = re.compile(r"\b[A-Z]{4}\b")

# Akronim empat huruf yang lazim muncul di berita ekonomi tetapi bukan emiten.
_BUKAN_EMITEN = frozenset(
    {
        "IHSG", "BUMN", "RUPS", "PLTS", "PLTU", "PLTA", "ESDM", "MSCI",
        "APBN", "APBD", "KPPU", "OJKK", "PPKM", "PPKM", "BPJS", "PPTK",
        "IPOS", "SUKU", "IPPU", "PLTG", "PLTP", "KPPS", "DPRD", "MPRS",
    }
)

MAKS_KODE_SEBELUM_RANGKUMAN = 5


def looks_like_roundup(article: Article, maks_kode: int = MAKS_KODE_SEBELUM_RANGKUMAN) -> bool:
    """True bila artikel menyebut banyak kode emiten sekaligus.

    Artikel semacam ini adalah rangkuman pasar ('asing lego 10 saham ini'),
    bukan berita tentang satu emiten. Sentimennya mengukur pasar secara umum,
    sehingga menjadikannya dasar keputusan untuk satu emiten menyesatkan.
    """
    teks = f"{article.title} {article.description}"
    kode = {k for k in _KODE_EMITEN.findall(teks) if k not in _BUKAN_EMITEN}
    return len(kode) > maks_kode


def clean_text(text: str, source: str = "") -> str:
    """Bersihkan satu potong teks berita.

    Suffix sumber dipangkas hanya bila cocok persis dengan nama sumber artikel,
    sehingga judul yang memuat tanda hubung biasa tidak ikut terpotong.
    """
    if not text:
        return ""

    result = html.unescape(text)
    result = _TAG.sub(" ", result)
    result = _TRUNCATION.sub(" ", result)
    result = _URL.sub(" ", result)

    if source:
        suffix = re.compile(
            r"\s*[-|–—]\s*" + re.escape(source) + r"\s*$", re.IGNORECASE
        )
        result = suffix.sub("", result)

    return _WHITESPACE.sub(" ", result).strip()


def _disebut(teks: str, ticker: Ticker) -> bool:
    haystack = teks.lower()
    needles = [ticker.name, ticker.code, *ticker.aliases]
    return any(
        re.search(r"\b" + re.escape(n.lower()) + r"\b", haystack)
        for n in needles
        if n
    )


def is_relevant(article: Article, ticker: Ticker) -> bool:
    """True bila artikel benar-benar membahas emiten ini.

    Judul diperlakukan sebagai pernyataan editor tentang isi artikel: bila
    emitennya disebut di sana, artikel itu memang tentang dia. Penyebutan yang
    hanya muncul di deskripsi diterima juga, kecuali artikelnya rangkuman pasar
    yang mendaftar banyak emiten sekaligus.
    """
    if _disebut(article.title, ticker):
        return True
    if not _disebut(article.description, ticker):
        return False
    return not looks_like_roundup(article)


def prepare(article: Article) -> str:
    """Gabungkan judul dan deskripsi yang sudah bersih, judul di depan."""
    title = clean_text(article.title, article.source)
    description = clean_text(article.description, article.source)
    if title and description:
        return f"{title}. {description}"
    return title or description


def prepare_articles(
    articles: Sequence[Article], ticker: Ticker
) -> list[tuple[Article, str]]:
    """Saring dan siapkan artikel untuk inferensi.

    Membuang artikel '[Removed]', artikel yang tidak menyebut emiten, dan
    artikel yang tidak menyisakan teks apa pun setelah dibersihkan.
    """
    prepared: list[tuple[Article, str]] = []
    for article in articles:
        if article.title.strip().lower() == _REMOVED:
            continue
        if not is_relevant(article, ticker):
            continue
        text = prepare(article)
        if not text:
            continue
        prepared.append((article, text))
    return prepared
