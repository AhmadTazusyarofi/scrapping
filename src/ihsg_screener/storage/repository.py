"""Akses SQLite untuk riwayat scan, alert, dan deduplikasi."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from ..models import ScanResult

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class Repository:
    """Pembungkus SQLite. Skema diterapkan otomatis saat inisialisasi."""

    def __init__(self, db_path: str | Path) -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.connection.commit()

    def start_run(self, started_at: datetime | None = None) -> int:
        moment = (started_at or datetime.now()).isoformat(timespec="seconds")
        cursor = self.connection.execute(
            "INSERT INTO runs (started_at, status) VALUES (?, 'running')", (moment,)
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def finish_run(
        self,
        run_id: int,
        status: str,
        scanned: int,
        candidates: int,
        alerts: int,
        notes: str = "",
    ) -> None:
        self.connection.execute(
            "UPDATE runs SET finished_at=?, status=?, scanned=?, candidates=?, "
            "alerts=?, notes=? WHERE id=?",
            (
                datetime.now().isoformat(timespec="seconds"),
                status,
                scanned,
                candidates,
                alerts,
                notes,
                run_id,
            ),
        )
        self.connection.commit()

    def record_result(
        self, run_id: int, result: ScanResult, as_of: date | None = None
    ) -> None:
        technical = result.technical
        sentiment = result.sentiment
        effective_as_of = as_of or (technical.as_of if technical else None)

        self.connection.execute(
            "INSERT INTO scan_results (run_id, symbol, as_of, decision, reason, close, "
            "indicators, sentiment_label, sentiment_score, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                result.symbol,
                effective_as_of.isoformat() if effective_as_of else None,
                result.decision.value,
                result.reason,
                technical.close if technical else None,
                json.dumps(technical.indicators) if technical else None,
                sentiment.label.value if sentiment else None,
                sentiment.score if sentiment else None,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        self.connection.commit()

    def record_alert(
        self,
        run_id: int,
        symbol: str,
        as_of: date,
        close: float,
        payload: dict,
        sent_at: datetime | None = None,
    ) -> None:
        self.connection.execute(
            "INSERT INTO alerts (run_id, symbol, as_of, close, payload, sent_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                run_id,
                symbol,
                as_of.isoformat(),
                close,
                json.dumps(payload, ensure_ascii=False),
                (sent_at or datetime.now()).isoformat(timespec="seconds"),
            ),
        )
        self.connection.commit()

    def recently_alerted(
        self, symbol: str, cooldown_days: int, now: datetime | None = None
    ) -> bool:
        """True bila simbol sudah dialert dalam cooldown_days hari terakhir."""
        cutoff = (now or datetime.now()) - timedelta(days=cooldown_days)
        row = self.connection.execute(
            "SELECT 1 FROM alerts WHERE symbol=? AND sent_at >= ? LIMIT 1",
            (symbol, cutoff.isoformat(timespec="seconds")),
        ).fetchone()
        return row is not None

    def close(self) -> None:
        self.connection.close()
