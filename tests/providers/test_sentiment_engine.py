import pytest

from ihsg_screener.errors import LabelMappingError
from ihsg_screener.models import SentimentLabel
from ihsg_screener.providers import sentiment_engine as se


def test_map_labels_menerima_label_bahasa_inggris():
    hasil = se.map_labels({0: "negative", 1: "neutral", 2: "positive"})

    assert hasil["negative"] is SentimentLabel.NEGATIF
    assert hasil["neutral"] is SentimentLabel.NETRAL
    assert hasil["positive"] is SentimentLabel.POSITIF


def test_map_labels_menerima_label_bahasa_indonesia():
    hasil = se.map_labels({0: "negatif", 1: "netral", 2: "positif"})

    assert hasil["positif"] is SentimentLabel.POSITIF


def test_map_labels_tidak_peduli_besar_kecil_huruf():
    assert se.map_labels({0: "POSITIVE"})["positive"] is SentimentLabel.POSITIF


def test_map_labels_menerima_label_dua_kelas():
    hasil = se.map_labels({0: "negative", 1: "positive"})

    assert set(hasil.values()) == {SentimentLabel.NEGATIF, SentimentLabel.POSITIF}


def test_map_labels_menolak_label_generik():
    with pytest.raises(LabelMappingError, match="LABEL_0"):
        se.map_labels({0: "LABEL_0", 1: "LABEL_1", 2: "LABEL_2"})


def test_map_labels_menolak_pemetaan_kosong():
    with pytest.raises(LabelMappingError, match="kosong"):
        se.map_labels({})


def test_engine_tidak_memuat_model_sampai_classify_dipanggil():
    engine = se.SentimentEngine("model-palsu", pipeline_factory=lambda name: _pipeline_palsu())

    assert engine.is_loaded is False


def test_classify_mengembalikan_label_dan_skor():
    engine = se.SentimentEngine("model-palsu", pipeline_factory=lambda name: _pipeline_palsu())

    hasil = engine.classify(["berita bagus", "berita buruk"])

    assert hasil[0] == (SentimentLabel.POSITIF, pytest.approx(0.91))
    assert hasil[1] == (SentimentLabel.NEGATIF, pytest.approx(0.88))
    assert engine.is_loaded is True


def test_classify_meneruskan_parameter_truncation_512():
    pipeline = _pipeline_palsu()
    engine = se.SentimentEngine("model-palsu", pipeline_factory=lambda name: pipeline)

    engine.classify(["teks"])

    assert pipeline.last_kwargs["truncation"] is True
    assert pipeline.last_kwargs["max_length"] == 512


def test_classify_daftar_kosong_tidak_memuat_model():
    engine = se.SentimentEngine("model-palsu", pipeline_factory=lambda name: _pipeline_palsu())

    assert engine.classify([]) == []
    assert engine.is_loaded is False


class _PipelinePalsu:
    def __init__(self):
        self.model = type("M", (), {"config": type("C", (), {"id2label": {0: "negative", 1: "positive"}})()})()
        self.last_kwargs = None

    def __call__(self, texts, **kwargs):
        self.last_kwargs = kwargs
        jawaban = {"berita bagus": ("positive", 0.91), "berita buruk": ("negative", 0.88)}
        return [
            {"label": jawaban.get(t, ("positive", 0.5))[0], "score": jawaban.get(t, ("positive", 0.5))[1]}
            for t in texts
        ]


def _pipeline_palsu():
    return _PipelinePalsu()


@pytest.mark.integration
def test_model_asli_dapat_dimuat_dan_labelnya_terpetakan():
    """Verifikasi asumsi §17.1 spec. Jalankan: pytest -m integration"""
    import yaml

    cfg = yaml.safe_load(open("config/settings.yaml", encoding="utf-8"))
    engine = se.SentimentEngine(cfg["sentiment"]["model"])

    hasil = engine.classify(["Kinerja perusahaan sangat baik dan laba meningkat tajam"])

    assert hasil[0][0] in set(SentimentLabel)
    assert 0.0 <= hasil[0][1] <= 1.0
