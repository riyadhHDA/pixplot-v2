"""Import de métadonnées (artiste, date, lieu, genre, style, source...) depuis un CSV.

Le CSV doit avoir une colonne ``path`` (absolue, ou relative au dossier du CSV) ;
chaque autre colonne devient une clé de métadonnée de l'œuvre correspondante.
La provenance (nom du fichier CSV) est enregistrée pour chaque valeur.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from . import db


@dataclass
class MetadataReport:
    rows: int = 0
    matched: int = 0
    unmatched: int = 0
    values: int = 0


def import_csv(csv_path: Path, catalog_path: Path, source: str | None = None) -> MetadataReport:
    csv_path = Path(csv_path).resolve()
    source = source or csv_path.name
    report = MetadataReport()
    conn = db.connect(catalog_path)
    ids = {r["path"]: r["id"] for r in conn.execute("SELECT id, path FROM artworks")}

    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or "path" not in reader.fieldnames:
            raise ValueError("Le CSV doit contenir une colonne 'path'")
        for row in reader:
            report.rows += 1
            p = Path(row.pop("path"))
            if not p.is_absolute():
                p = csv_path.parent / p
            artwork_id = ids.get(p.resolve().as_posix())
            if artwork_id is None:
                report.unmatched += 1
                continue
            report.matched += 1
            values = [(artwork_id, k, v, source) for k, v in row.items() if k and v not in (None, "")]
            conn.executemany(
                "INSERT OR REPLACE INTO metadata(artwork_id, key, value, source) VALUES (?, ?, ?, ?)", values)
            report.values += len(values)
    conn.commit()
    conn.close()
    return report


def get_metadata(conn, artwork_ids: list[int]) -> dict[int, dict[str, str]]:
    out: dict[int, dict[str, str]] = {i: {} for i in artwork_ids}
    for start in range(0, len(artwork_ids), 900):
        chunk = artwork_ids[start:start + 900]
        q = f"SELECT artwork_id, key, value FROM metadata WHERE artwork_id IN ({','.join('?' * len(chunk))})"
        for r in conn.execute(q, chunk):
            out[r[0]][r[1]] = r[2]
    return out
