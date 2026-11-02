import pytest

from ihsg_screener.core import textproc
from ihsg_screener.models import Article, Ticker

BBRI = Ticker(symbol="BBRI.JK", name="Bank Rakyat Indonesia", aliases=("BBRI", "BRI"))


def _article(title="", description="", source="Detikcom"):
    return Article(
        title=title,
        description=description,
        url="https://contoh.id/a",
        source=source,
        published_at="2026-08-25T10:00:00Z",
    )


def test_clean_text_membuang_tag_html_dan_entitas():
    assert textproc.clean_text("<b>Laba</b> naik &amp; kuat") == "Laba naik & kuat"


def test_clean_text_membuang_url():
    hasil = textproc.clean_text("Baca di https://contoh.id/berita/123 sekarang")

    assert "https" not in hasil
    assert hasil == "Baca di sekarang"


def test_clean_text_membuang_penanda_potongan_newsapi():
    assert textproc.clean_text("Laba naik tajam… [+1423 chars]") == "Laba naik tajam"


def test_clean_text_membuang_suffix_sumber():
    hasil = textproc.clean_text("BBRI cetak laba - Detikcom", source="Detikcom")

    assert hasil == "BBRI cetak laba"


def test_clean_text_mempertahankan_tanda_hubung_yang_bukan_suffix_sumber():
    hasil = textproc.clean_text("Laba naik 10 - 15 persen", source="Detikcom")

    assert hasil == "Laba naik 10 - 15 persen"


def test_clean_text_merapatkan_spasi_berlebih():
    assert textproc.clean_text("Laba    naik\n\ntajam") == "Laba naik tajam"


def test_is_relevant_menerima_kecocokan_nama_perusahaan():
    artikel = _article(title="Bank Rakyat Indonesia cetak laba", description="")

    assert textproc.is_relevant(artikel, BBRI) is True


def test_is_relevant_menerima_kecocokan_alias():
    artikel = _article(title="Saham BBRI menguat", description="")

    assert textproc.is_relevant(artikel, BBRI) is True


def test_is_relevant_tidak_peduli_besar_kecil_huruf():
    artikel = _article(title="saham bri menguat", description="")

    assert textproc.is_relevant(artikel, BBRI) is True


def test_is_relevant_menolak_artikel_yang_tidak_menyebut_emiten():
    artikel = _article(title="IHSG ditutup menguat", description="Indeks naik 1 persen")

    assert textproc.is_relevant(artikel, BBRI) is False


def test_is_relevant_menolak_alias_yang_hanya_bagian_kata():
    artikel = _article(title="Negara BRICS bertemu", description="")

    assert textproc.is_relevant(artikel, BBRI) is False


def test_prepare_menempatkan_judul_di_depan():
    artikel = _article(title="BBRI cetak laba", description="Laba naik 12 persen")

    assert textproc.prepare(artikel) == "BBRI cetak laba. Laba naik 12 persen"


def test_prepare_menangani_deskripsi_kosong():
    assert textproc.prepare(_article(title="BBRI cetak laba")) == "BBRI cetak laba"


def test_prepare_articles_membuang_artikel_removed():
    artikel = [
        _article(title="[Removed]", description="[Removed]"),
        _article(title="BBRI cetak laba", description="Naik 12 persen"),
    ]

    hasil = textproc.prepare_articles(artikel, BBRI)

    assert len(hasil) == 1
    assert hasil[0][1] == "BBRI cetak laba. Naik 12 persen"


def test_prepare_articles_membuang_artikel_tidak_relevan():
    artikel = [
        _article(title="IHSG ditutup menguat", description="Indeks naik"),
        _article(title="BBRI cetak laba", description="Naik 12 persen"),
    ]

    hasil = textproc.prepare_articles(artikel, BBRI)

    assert [a.title for a, _ in hasil] == ["BBRI cetak laba"]


def test_prepare_articles_membuang_teks_yang_kosong_setelah_dibersihkan():
    # Relevan (mengandung 'BBRI'), tetapi tidak menyisakan teks setelah URL dibuang.
    artikel = [_article(title="https://contoh.id/BBRI", description="")]

    assert textproc.is_relevant(artikel[0], BBRI) is True
    assert textproc.prepare_articles(artikel, BBRI) == []


# --- Penolakan artikel rangkuman pasar -------------------------------------
# RSS memperbesar volume, sehingga juga memperbesar masalah yang sudah
# diantisipasi §8 spec: artikel yang menyebut sepuluh kode emiten sekaligus
# menghasilkan verdict yang sebenarnya mengukur sentimen berita lain.

RANGKUMAN = "Asing lego BBCA, BMRI, ASII, UNTR, ADRO, PTBA, INCO, MEDC saat IHSG menguat"


def test_looks_like_roundup_mengenali_daftar_banyak_emiten():
    assert textproc.looks_like_roundup(_article(title=RANGKUMAN)) is True


def test_looks_like_roundup_tidak_menganggap_berita_tunggal_sebagai_rangkuman():
    artikel = _article(title="BBRI cetak laba bersih Rp 60 triliun", description="Naik 12 persen")

    assert textproc.looks_like_roundup(artikel) is False


def test_looks_like_roundup_tidak_terkecoh_akronim_bukan_emiten():
    artikel = _article(
        title="IHSG dan BUMN jadi sorotan RUPS",
        description="Proyek PLTS dan PLTU dibahas bersama ESDM",
    )

    assert textproc.looks_like_roundup(artikel) is False


def test_relevan_bila_disebut_di_judul_meski_artikel_rangkuman():
    # Judul adalah pernyataan editor tentang isi artikel; kalau emitennya
    # disebut di sana, artikel itu memang tentang dia.
    artikel = _article(title="BBRI " + RANGKUMAN, description="")

    assert textproc.is_relevant(artikel, BBRI) is True


def test_tidak_relevan_bila_hanya_muncul_di_deskripsi_artikel_rangkuman():
    artikel = _article(title="Asing lego saham perbankan", description=RANGKUMAN + " BBRI")

    assert textproc.is_relevant(artikel, BBRI) is False


def test_relevan_bila_muncul_di_deskripsi_artikel_biasa():
    artikel = _article(
        title="Bank pelat merah bagikan dividen",
        description="Bank Rakyat Indonesia mengumumkan dividen tahun ini",
    )

    assert textproc.is_relevant(artikel, BBRI) is True
