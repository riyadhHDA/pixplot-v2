"""Extraction des vecteurs pour tout le catalogue, par lots, reprenable.

Contenu d'un run ``features/<encodeur>_<horodatage>/`` :

    manifest.json   modèle, paramètres, mesures (images/s, VRAM)
    ids.npy         (N,)       int64   identifiants catalogue, dans l'ordre des lignes
    global.npy      (N, D)     float16 vecteur global normalisé
    regions.npy     (N, R, D)  float16 vecteurs régionaux (R = 21 par défaut)
    status.npy      (N,)       int8    0 = à faire · 1 = ok · 2 = échec
    failures.jsonl             une ligne par image en échec, avec la raison

L'ordre des lignes est fixé une fois pour toutes par ``ids.npy`` : une image qui échoue
garde sa ligne (marquée 2), elle ne décale jamais les autres (bug du PixPlot v1).
"""

from __future__ import annotations

import json
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

import numpy as np
from numpy.lib.format import open_memmap

from ..catalog import db
from ..encoders.base import Encoder
from ..imageio import open_image
from ..runs import Run, create_run, list_runs
from .regions import DEFAULT_GRIDS, letterbox_mask, pool_regions, region_count

TODO, OK, FAILED = 0, 1, 2


def _params(encoder: Encoder, limit: int | None, grids: tuple[int, ...]) -> dict:
    return {**encoder.describe(), "limit": limit, "region_grids": list(grids)}


def _find_resumable(encoder: Encoder, params: dict, runs_dir: Path) -> Run | None:
    for run in reversed(list_runs("features", name=encoder.name, status=None, runs_dir=runs_dir)):
        if run.manifest["status"] in ("running", "failed") and run.manifest["params"] == params:
            return run
    return None


def extract(
    encoder: Encoder,
    catalog_path: Path,
    runs_dir: Path,
    limit: int | None = None,
    batch_size: int = 16,
    workers: int = 4,
    resume: bool = True,
    grids: tuple[int, ...] = DEFAULT_GRIDS,
    progress: Callable[[int, int], None] | None = None,
    flush_every: int = 20,
) -> Run:
    conn = db.connect(catalog_path)
    params = _params(encoder, limit, grids)
    run = _find_resumable(encoder, params, runs_dir) if resume else None

    if run is None:
        ids = db.ok_ids(conn, limit)
        if not ids:
            raise RuntimeError("Aucune œuvre au statut 'ok' dans le catalogue : lancez d'abord `pixplot ingest`.")
        run = create_run("features", encoder.name, params, runs_dir=runs_dir)
        n = len(ids)
        np.save(run.path / "ids.npy", np.asarray(ids, dtype=np.int64))
        open_memmap(run.path / "global.npy", "w+", np.float16, (n, encoder.dim)).flush()
        if encoder.patch_size:
            open_memmap(run.path / "regions.npy", "w+", np.float16, (n, region_count(grids), encoder.dim)).flush()
        open_memmap(run.path / "status.npy", "w+", np.int8, (n,)).flush()
    else:
        run.manifest.update(status="running", resumed=run.manifest.get("resumed", 0) + 1)
        run.manifest.pop("error", None)
        run.save()

    ids = np.load(run.path / "ids.npy")
    g_vec = open_memmap(run.path / "global.npy", "r+")
    r_vec = open_memmap(run.path / "regions.npy", "r+") if encoder.patch_size else None
    status = open_memmap(run.path / "status.npy", "r+")
    paths = {i: r["path"] for i, r in db.get_artworks(conn, ids.tolist()).items()}
    conn.close()

    todo = np.flatnonzero(status == TODO)
    batches = [todo[i:i + batch_size] for i in range(0, len(todo), batch_size)]
    total, done_before = len(ids), int((status != TODO).sum())
    size = encoder.input_size

    def load(row: int):
        try:
            img = open_image(paths[int(ids[row])], target=size)
            arr, box = encoder.preprocess(img)
            return row, arr, box, None
        except Exception as exc:
            return row, None, None, f"{type(exc).__name__}: {exc}"

    processed, start = 0, time.perf_counter()
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool, \
                open(run.path / "failures.jsonl", "a", encoding="utf-8") as failures:
            queue: deque = deque()
            pending = iter(batches)

            def prefetch():
                b = next(pending, None)
                if b is not None:
                    queue.append([pool.submit(load, r) for r in b])

            prefetch()
            prefetch()  # toujours un lot d'avance pendant que le GPU calcule
            n_batches = 0
            while queue:
                items = [f.result() for f in queue.popleft()]
                prefetch()

                good = [it for it in items if it[3] is None]
                for row, _, _, err in items:
                    if err is not None:
                        status[row] = FAILED
                        failures.write(json.dumps({"id": int(ids[row]), "error": err}, ensure_ascii=False) + "\n")

                if good:
                    rows = np.array([it[0] for it in good])
                    out = encoder.encode(np.stack([it[1] for it in good]))
                    g_vec[rows] = out.global_vectors.astype(np.float16)
                    if r_vec is not None and out.patch_grid is not None:
                        masks = np.stack([letterbox_mask(it[2], size, encoder.patch_size) for it in good])
                        r_vec[rows] = pool_regions(out.patch_grid, grids, masks).astype(np.float16)
                    status[rows] = OK

                processed += len(items)
                n_batches += 1
                if n_batches % flush_every == 0:
                    _flush(g_vec, r_vec, status)
                    failures.flush()
                if progress:
                    progress(done_before + processed, total)
    except BaseException as exc:
        _flush(g_vec, r_vec, status)
        run.fail("interrompu par l'utilisateur" if isinstance(exc, KeyboardInterrupt) else exc)
        raise

    _flush(g_vec, r_vec, status)
    elapsed = time.perf_counter() - start
    run.complete(
        count=total,
        ok=int((status == OK).sum()),
        failed=int((status == FAILED).sum()),
        seconds_last_session=round(elapsed, 1),
        images_per_second=round(processed / elapsed, 1) if elapsed > 0 and processed else None,
        **encoder.runtime_stats(),
    )
    return run


def _flush(*arrays) -> None:
    for a in arrays:
        if a is not None:
            a.flush()
