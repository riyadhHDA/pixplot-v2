"""Carnet de recherche : garder ses pistes, ses sélections et ses comparaisons.

Un fichier SQLite par dossier de données (``<données>/notebook.sqlite``), séparé du
catalogue : il contient le travail de l'historien, pas des données recalculables. Chaque
entrée garde les œuvres concernées, une note libre et le contexte qui l'a produite
(recherche, détail tracé, comparaison, espace de voisinage...), pour pouvoir y revenir et
la citer.

Exportable en Markdown (lisible partout) et en Research Pack (une entrée = un dossier).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

KINDS = ("note", "oeuvre", "selection", "recherche", "detail", "comparaison", "groupe")

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created TEXT NOT NULL,
    updated TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    artwork_ids TEXT NOT NULL DEFAULT '[]',
    context TEXT NOT NULL DEFAULT '{}'
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Notebook:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _row(r: sqlite3.Row) -> dict:
        return {"id": r["id"], "created": r["created"], "updated": r["updated"], "kind": r["kind"],
                "title": r["title"], "note": r["note"], "artwork_ids": json.loads(r["artwork_ids"]),
                "context": json.loads(r["context"])}

    def add(self, title: str, kind: str = "note", note: str = "", artwork_ids: list[int] | None = None,
            context: dict | None = None) -> dict:
        if kind not in KINDS:
            raise ValueError(f"Type d'entrée inconnu : {kind} (choix : {', '.join(KINDS)})")
        title = (title or "").strip() or "Sans titre"
        now = _now()
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO entries (created, updated, kind, title, note, artwork_ids, context) VALUES (?,?,?,?,?,?,?)",
                (now, now, kind, title[:300], note or "", json.dumps([int(i) for i in artwork_ids or []]),
                 json.dumps(context or {}, ensure_ascii=False)))
            return self.get(cur.lastrowid, conn)

    def get(self, entry_id: int, conn: sqlite3.Connection | None = None) -> dict | None:
        c = conn or self._conn()
        r = c.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
        return self._row(r) if r else None

    def list(self, query: str = "", limit: int = 500) -> list[dict]:
        sql, args = "SELECT * FROM entries", []
        if query:
            sql += " WHERE title LIKE ? OR note LIKE ?"
            args = [f"%{query}%"] * 2
        sql += " ORDER BY id DESC LIMIT ?"
        with self._conn() as conn:
            return [self._row(r) for r in conn.execute(sql, [*args, limit])]

    def update(self, entry_id: int, title: str | None = None, note: str | None = None,
               artwork_ids: list[int] | None = None) -> dict | None:
        sets, args = ["updated = ?"], [_now()]
        if title is not None:
            sets.append("title = ?"); args.append(title.strip()[:300] or "Sans titre")
        if note is not None:
            sets.append("note = ?"); args.append(note)
        if artwork_ids is not None:
            sets.append("artwork_ids = ?"); args.append(json.dumps([int(i) for i in artwork_ids]))
        with self._conn() as conn:
            conn.execute(f"UPDATE entries SET {', '.join(sets)} WHERE id = ?", [*args, entry_id])
            return self.get(entry_id, conn)

    def delete(self, entry_id: int) -> bool:
        with self._conn() as conn:
            return conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,)).rowcount > 0

    def to_markdown(self, label=lambda i: f"Œuvre {i}") -> str:
        """Le carnet entier, du plus ancien au plus récent. ``label(id)`` décrit une œuvre."""
        lines = ["# Carnet de recherche PixPlot", "",
                 f"Exporté le {datetime.now().strftime('%d/%m/%Y à %H:%M')}.", ""]
        for e in reversed(self.list(limit=100_000)):
            lines += [f"## {e['title']}", "",
                      f"*{e['kind']} · {e['created'][:16].replace('T', ' ')} UTC · entrée n° {e['id']}*", ""]
            if e["note"]:
                lines += [e["note"], ""]
            ctx = {k: v for k, v in e["context"].items() if v not in (None, "", [], {})}
            if ctx:
                lines += ["Contexte : " + " ; ".join(f"{k} = {v}" for k, v in ctx.items()), ""]
            for i in e["artwork_ids"][:200]:
                lines.append(f"- n° {i} — {label(i)}")
            if len(e["artwork_ids"]) > 200:
                lines.append(f"- … et {len(e['artwork_ids']) - 200} autres")
            lines.append("")
        return "\n".join(lines)
