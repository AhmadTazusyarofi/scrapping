import json
from datetime import date, datetime

import pytest

from ihsg_screener.models import Decision, ScanResult, SentimentLabel, SentimentVerdict, TechnicalSignal
from ihsg_screener.storage.repository import Repository


@pytest.fixture()
def repo(tmp_path):
    r = Repository(tmp_path / "sub" / "scanner.db")
    yield r
    r.close()


def _signal(symbol="BBRI.JK"):
    return TechnicalSignal(
        symbol=symbol,
        is_bullish=True,
        close=5000.0,
        as_of=date(2026, 8, 25),
        indicators={"sma_fast": 5010.0, "sma_slow": 4900.0},
        passed_rules=("sma_cross",),
        failed_rules=(),
    )


def _verdict():
    return SentimentVerdict(
        label=SentimentLabel.POSITIF, score=0.85, analyzed_count=2, rejected_count=1
    )


def test_membuat_direktori_induk_dan_tabel(tmp_path):
    repo = Repository(tmp_path / "baru" / "scanner.db")

    tabel = {row[0] for row in repo.connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    repo.close()

    assert {"runs", "scan_results", "alerts"} <= tabel


def test_start_run_mengembalikan_id_yang_bertambah(repo):
    pertama = repo.start_run()
    kedua = repo.start_run()

    assert kedua > pertama


def test_finish_run_menyimpan_ringkasan(repo):
    run_id = repo.start_run()

    repo.finish_run(run_id, status="ok", scanned=5, candidates=2, alerts=1, notes="uji")

    baris = repo.connection.execute(
        "SELECT status, scanned, candidates, alerts, notes, finished_at FROM runs WHERE id=?",
        (run_id,),
    ).fetchone()
    assert baris[0] == "ok"
    assert baris[1:5] == (5, 2, 1, "uji")
    assert baris[5] is not None


def test_record_result_menyimpan_indikator_sebagai_json(repo):
    run_id = repo.start_run()
    result = ScanResult(
        symbol="BBRI.JK",
        decision=Decision.BUY_ALERT,
        reason="lolos",
        technical=_signal(),
        sentiment=_verdict(),
    )

    repo.record_result(run_id, result)

    baris = repo.connection.execute(
        "SELECT symbol, decision, close, indicators, sentiment_label, sentiment_score, as_of "
        "FROM scan_results WHERE run_id=?",
        (run_id,),
    ).fetchone()
    assert baris[0] == "BBRI.JK"
    assert baris[1] == "BUY_ALERT"
    assert baris[2] == pytest.approx(5000.0)
    assert json.loads(baris[3])["sma_fast"] == pytest.approx(5010.0)
    assert baris[4] == "POSITIF"
    assert baris[5] == pytest.approx(0.85)
    assert baris[6] == "2026-08-25"


def test_record_result_menerima_hasil_tanpa_teknikal(repo):
    run_id = repo.start_run()
    result = ScanResult(symbol="XXXX.JK", decision=Decision.SKIPPED_NO_DATA, reason="kosong")

    repo.record_result(run_id, result)

    baris = repo.connection.execute(
        "SELECT decision, close, sentiment_label FROM scan_results WHERE symbol='XXXX.JK'"
    ).fetchone()
    assert baris == ("SKIPPED_NO_DATA", None, None)


def test_recently_alerted_false_bila_belum_pernah(repo):
    assert repo.recently_alerted("BBRI.JK", cooldown_days=5) is False


def test_recently_alerted_true_di_dalam_cooldown(repo):
    run_id = repo.start_run()
    kemarin = datetime(2026, 8, 24, 18, 0, 0)
    repo.record_alert(run_id, "BBRI.JK", date(2026, 8, 24), 5000.0, {"a": 1}, sent_at=kemarin)

    hasil = repo.recently_alerted("BBRI.JK", cooldown_days=5, now=datetime(2026, 8, 25, 18, 0, 0))

    assert hasil is True


def test_recently_alerted_false_setelah_cooldown_lewat(repo):
    run_id = repo.start_run()
    lama = datetime(2026, 8, 1, 18, 0, 0)
    repo.record_alert(run_id, "BBRI.JK", date(2026, 8, 1), 5000.0, {"a": 1}, sent_at=lama)

    hasil = repo.recently_alerted("BBRI.JK", cooldown_days=5, now=datetime(2026, 8, 25, 18, 0, 0))

    assert hasil is False


def test_recently_alerted_hanya_melihat_simbol_yang_diminta(repo):
    run_id = repo.start_run()
    repo.record_alert(run_id, "TLKM.JK", date(2026, 8, 25), 3000.0, {},
                      sent_at=datetime(2026, 8, 25, 18, 0, 0))

    hasil = repo.recently_alerted("BBRI.JK", cooldown_days=5, now=datetime(2026, 8, 25, 19, 0, 0))

    assert hasil is False


def test_record_alert_menyimpan_payload_json(repo):
    run_id = repo.start_run()

    repo.record_alert(run_id, "BBRI.JK", date(2026, 8, 25), 5000.0, {"rules": ["sma_cross"]})

    payload = repo.connection.execute(
        "SELECT payload FROM alerts WHERE symbol='BBRI.JK'"
    ).fetchone()[0]
    assert json.loads(payload)["rules"] == ["sma_cross"]
