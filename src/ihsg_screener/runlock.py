"""Lock file sederhana agar dua run terjadwal tidak tumpang tindih."""

from __future__ import annotations

import os
from pathlib import Path

from .errors import ScreenerError


class AlreadyRunningError(ScreenerError):
    """Run lain masih berjalan."""


class RunLock:
    """Context manager berbasis pembuatan file eksklusif."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def __enter__(self) -> "RunLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise AlreadyRunningError(
                f"Run lain sedang berjalan (lock: {self.path}). "
                "Bila yakin tidak ada, hapus file tersebut secara manual."
            ) from exc
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.path.unlink(missing_ok=True)
