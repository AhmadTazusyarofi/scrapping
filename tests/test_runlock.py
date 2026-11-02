import pytest

from ihsg_screener.runlock import AlreadyRunningError, RunLock


def test_lock_membuat_dan_menghapus_file(tmp_path):
    path = tmp_path / "scanner.lock"

    with RunLock(path):
        assert path.exists()

    assert not path.exists()


def test_lock_kedua_ditolak_selama_yang_pertama_aktif(tmp_path):
    path = tmp_path / "scanner.lock"

    with RunLock(path):
        with pytest.raises(AlreadyRunningError):
            with RunLock(path):
                pass


def test_lock_dilepas_meski_terjadi_exception(tmp_path):
    path = tmp_path / "scanner.lock"

    with pytest.raises(ValueError):
        with RunLock(path):
            raise ValueError("boom")

    assert not path.exists()


def test_lock_membuat_direktori_induk(tmp_path):
    path = tmp_path / "dalam" / "scanner.lock"

    with RunLock(path):
        assert path.exists()
