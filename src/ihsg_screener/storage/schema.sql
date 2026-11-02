CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    status       TEXT NOT NULL,
    scanned      INTEGER DEFAULT 0,
    candidates   INTEGER DEFAULT 0,
    alerts       INTEGER DEFAULT 0,
    notes        TEXT
);

CREATE TABLE IF NOT EXISTS scan_results (
    id              INTEGER PRIMARY KEY,
    run_id          INTEGER NOT NULL REFERENCES runs(id),
    symbol          TEXT NOT NULL,
    as_of           TEXT,
    decision        TEXT NOT NULL,
    reason          TEXT,
    close           REAL,
    indicators      TEXT,
    sentiment_label TEXT,
    sentiment_score REAL,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY,
    run_id      INTEGER NOT NULL REFERENCES runs(id),
    symbol      TEXT NOT NULL,
    as_of       TEXT NOT NULL,
    close       REAL NOT NULL,
    payload     TEXT NOT NULL,
    sent_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_alerts_symbol_sent ON alerts(symbol, sent_at);
CREATE INDEX IF NOT EXISTS idx_scan_run ON scan_results(run_id);
