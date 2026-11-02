"""Menegakkan aturan struktural spec: core/ tidak boleh menyentuh I/O."""

import ast
from pathlib import Path

import pytest

CORE = Path(__file__).resolve().parents[1] / "src" / "ihsg_screener" / "core"
TERLARANG = {"yfinance", "requests", "transformers", "torch", "sqlite3", "urllib"}


def _modul_yang_diimpor(path: Path) -> set[str]:
    pohon = ast.parse(path.read_text(encoding="utf-8"))
    hasil: set[str] = set()
    for node in ast.walk(pohon):
        if isinstance(node, ast.Import):
            hasil.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            hasil.add(node.module.split(".")[0])
    return hasil


@pytest.mark.parametrize("path", sorted(CORE.glob("*.py")), ids=lambda p: p.name)
def test_core_tidak_mengimpor_lapisan_io(path):
    pelanggaran = _modul_yang_diimpor(path) & TERLARANG

    assert not pelanggaran, (
        f"{path.name} mengimpor {sorted(pelanggaran)}. "
        "Logika keputusan sedang bocor ke lapisan I/O."
    )


def test_core_memuat_seluruh_modul_yang_dijanjikan_spec():
    nama = {p.stem for p in CORE.glob("*.py")} - {"__init__"}

    assert nama == {"indicators", "strategy", "textproc", "sentiment"}
