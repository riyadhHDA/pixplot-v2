"""Ingestion : repérer les images, les identifier, détecter les doublons, faire les vignettes.

Incrémental et reprenable : relancer ``ingest`` sur les mêmes dossiers ne retraite que
les nouvelles images et celles restées ``pending`` après une interruption.
Une image illisible est marquée ``error`` avec la raison ; elle ne bloque rien.
"""

from __future__ import annotations

import hashlib
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
from PIL import Image

from ..imageio import is_image_path, open_image, oriented_size
from . import db

THUMB_SIZES = (64, 256, 1024)
THUMB_FORMAT = "webp"


def thumb_path(thumbs_dir: Path, artwork_id: int, size: int) -> Path:
    # Sous-dossiers de 1000 fichiers pour ne pas avoir 500 000 fichiers dans un dossier.
    return Path(thumbs_dir) / str(size) / f"{artwork_id // 1000:04d}" / f"{artwork_id}.{THUMB_FORMAT}"


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def dhash(im: Image.Image, size: int = 8) -> str:
    """Empreinte perceptuelle 64 bits : proche pour deux scans d'une même œuvre."""
    g = np.asarray(im.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS), dtype=np.int16)
    bits = (g[:, 1:] > g[:, :-1]).flatten()
    return f"{int(''.join('1' if b else '0' for b in bits), 2):016x}"


def process_one(args: tuple[int, str, str]) -> dict:
    """Traite une image (exécuté dans un processus séparé)."""
    artwork_id, path, thumbs_dir = args
    p = Path(path)
    try:
        with Image.open(p) as probe:
            fmt = probe.format
            width, height = oriented_size(probe)
        im = open_image(p, target=max(THUMB_SIZES))
        for size in THUMB_SIZES:
            out = thumb_path(Path(thumbs_dir), artwork_id, size)
            out.parent.mkdir(parents=True, exist_ok=True)
            t = im.copy()
            t.thumbnail((size, size), Image.Resampling.LANCZOS)
            t.save(out, THUMB_FORMAT, quality=82, method=4)
        return {
            "id": artwork_id, "status": "ok", "sha256": sha256_file(p), "dhash": dhash(im),
            "width": width, "height": height, "format": fmt, "bytes": p.stat().st_size, "error": None,
        }
    except Exception as exc:  # image corrompue, format inconnu, fichier disparu...
        return {"id": artwork_id, "status": "error", "error": f"{type(exc).__name__}: {exc}"}


def scan(paths: Iterable[str | Path]) -> list[Path]:
    """Fichiers images sous ``paths`` (dossiers parcourus récursivement), triés."""
    found: set[Path] = set()
    for p in map(Path, paths):
        if p.is_dir():
            found.update(f.resolve() for f in p.rglob("*") if f.is_file() and is_image_path(f))
        elif p.is_file() and is_image_path(p):
            found.add(p.resolve())
    return sorted(found)


@dataclass
class IngestReport:
    discovered: int = 0
    new: int = 0
    processed: int = 0
    ok: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)
    duplicates: int = 0


def ingest(
    paths: Iterable[str | Path],
    catalog_path: Path,
    thumbs_dir: Path,
    workers: int | None = None,
    limit: int | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> IngestReport:
    report = IngestReport()
    conn = db.connect(catalog_path)
    files = scan(paths)
    report.discovered = len(files)

    # 1) Enregistrer les nouveaux chemins (attribue les identifiants stables).
    before = conn.total_changes
    conn.executemany("INSERT OR IGNORE INTO artworks(path) VALUES (?)", [(f.as_posix(),) for f in files])
    conn.commit()
    report.new = conn.total_changes - before

    # 2) Traiter tout ce qui est en attente (nouveau ou interrompu).
    sql = "SELECT id, path FROM artworks WHERE status = 'pending' ORDER BY id"
    if limit:
        sql += f" LIMIT {int(limit)}"
    todo = [(r["id"], r["path"], str(thumbs_dir)) for r in conn.execute(sql)]
    total = len(todo)
    if not total:
        return report

    workers = workers if workers is not None else max(1, (os.cpu_count() or 2) - 1)
    pool = ProcessPoolExecutor(max_workers=workers) if workers > 1 else None
    results = pool.map(process_one, todo, chunksize=8) if pool else map(process_one, todo)

    try:
        for i, res in enumerate(results, 1):
            _save_result(conn, res, report)
            if i % 200 == 0:
                conn.commit()
            if progress:
                progress(i, total)
    finally:
        conn.commit()
        if pool:
            pool.shutdown()
    conn.close()
    return report


def _save_result(conn, res: dict, report: IngestReport) -> None:
    report.processed += 1
    if res["status"] == "error":
        conn.execute("UPDATE artworks SET status='error', error=? WHERE id=?", (res["error"], res["id"]))
        path = conn.execute("SELECT path FROM artworks WHERE id=?", (res["id"],)).fetchone()[0]
        report.errors.append((path, res["error"]))
        return

    original = conn.execute(
        "SELECT id FROM artworks WHERE sha256=? AND status='ok' AND id<>? ORDER BY id LIMIT 1",
        (res["sha256"], res["id"]),
    ).fetchone()
    status = "duplicate" if original else "ok"
    conn.execute(
        """UPDATE artworks SET status=?, sha256=?, dhash=?, width=?, height=?, format=?, bytes=?,
           duplicate_of=?, error=NULL WHERE id=?""",
        (status, res["sha256"], res["dhash"], res["width"], res["height"], res["format"],
         res["bytes"], original[0] if original else None, res["id"]),
    )
    if original:
        report.duplicates += 1
    else:
        report.ok += 1
