"""Catalogue SQLite : une ligne par œuvre, identifiant stable.

Statuts : ``pending`` (repérée, pas encore traitée) · ``ok`` · ``error`` (illisible,
écartée et journalisée) · ``duplicate`` (copie exacte d'une œuvre déjà présente).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS artworks (
    id            INTEGER PRIMARY KEY,
    path          TEXT NOT NULL UNIQUE,
    status        TEXT NOT NULL DEFAULT 'pending',
    sha256        TEXT,
    dhash         TEXT,
    width         INTEGER,
    height        INTEGER,
    format        TEXT,
    bytes         INTEGER,
    duplicate_of  INTEGER REFERENCES artworks(id),
    error         TEXT,
    added         TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_artworks_sha256 ON artworks(sha256);
CREATE INDEX IF NOT EXISTS idx_artworks_status ON artworks(status);

-- Métadonnées libres (artiste, date, lieu, source, droits...) : import à venir.
CREATE TABLE IF NOT EXISTS metadata (
    artwork_id  INTEGER NOT NULL REFERENCES artworks(id),
    key         TEXT NOT NULL,
    value       TEXT,
    source      TEXT,
    PRIMARY KEY (artwork_id, key)
);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn


def ok_ids(conn: sqlite3.Connection, limit: int | None = None) -> list[int]:
    sql = "SELECT id FROM artworks WHERE status = 'ok' ORDER BY id"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return [r[0] for r in conn.execute(sql)]


def get_artworks(conn: sqlite3.Connection, ids: list[int]) -> dict[int, sqlite3.Row]:
    rows = {}
    for start in range(0, len(ids), 900):  # limite de paramètres SQLite
        chunk = ids[start:start + 900]
        q = f"SELECT * FROM artworks WHERE id IN ({','.join('?' * len(chunk))})"
        rows.update({r["id"]: r for r in conn.execute(q, chunk)})
    return rows


def find_by_path(conn: sqlite3.Connection, path: str | Path) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM artworks WHERE path = ?", (Path(path).resolve().as_posix(),)
    ).fetchone()


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    return dict(conn.execute("SELECT status, COUNT(*) FROM artworks GROUP BY status").fetchall())
