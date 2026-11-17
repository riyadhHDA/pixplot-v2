"""Chercher une zone avec des mots : index des zones d'œuvres vues par SigLIP 2.

Le banc d'essai RichArt (ARCHITECTURE § 19) a montré que la meilleure façon de retrouver
« une auréole » ou « le clocher au fond à gauche » est de passer **la zone découpée** dans
SigLIP 2 — mieux que TIPSv2. SigLIP 2 ne donnant pas de vecteur par zone, on découpe chaque
œuvre selon des grilles 2 × 2 et 4 × 4 (20 zones) et on passe chaque zone dans le modèle.

Deux étapes, enchaînées par ``pixplot zones`` :

1. **Extraction** (GPU, reprenable) : run ``features/zones_<encodeur>_<horodatage>/`` avec
   ``ids.npy``, ``zones.npy`` (N, 20, D) en float16 et ``done.npy`` (œuvres traitées). Les
   zones sont découpées dans les vignettes de 1024 px (rapides à lire) ; chaque zone est
   ensuite mise au format du modèle sans être recadrée (letterbox).
2. **Index** : run ``index/textzones_<…>/`` — PCA à 256 dimensions, index FAISS en float16.

Recherche : la phrase est encodée par SigLIP 2 puis projetée dans la même PCA. Les vecteurs
de zones sont projetés **sans être renormalisés** : le produit scalaire avec la requête vaut
alors q·v − q·moyenne, dont le second terme est le même pour toutes les zones — le
classement par similarité cosinus est préservé (à la perte de la PCA près).
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from ..features.extract import OK
from ..imageio import open_image
from ..runs import Run, create_run, list_runs

GRIDS = (2, 4)
PCA_DIM = 256
SEED = 42


def zone_boxes(grids: tuple[int, ...] = GRIDS) -> list[tuple[int, tuple[float, float, float, float]]]:
    """(taille de grille, cadre [x0, y0, x1, y1] en fractions de l'image)."""
    return [(g, (gx / g, gy / g, (gx + 1) / g, (gy + 1) / g)) for g in grids for gy in range(g) for gx in range(g)]


def crops(image, boxes) -> list:
    w, h = image.size
    return [image.crop((int(x0 * w), int(y0 * h), max(int(x1 * w), int(x0 * w) + 1), max(int(y1 * h), int(y0 * h) + 1)))
            for _, (x0, y0, x1, y1) in boxes]


# ------------------------------------------------------------------ extraction
def find_zone_run(runs_dir: Path | None, complete_only: bool = False) -> Run | None:
    runs = [r for r in list_runs("features", status=None, runs_dir=runs_dir, include_zones=True)
            if r.manifest["name"].startswith("zones_")]
    if complete_only:
        runs = [r for r in runs if r.manifest.get("status") == "complete"]
    return runs[-1] if runs else None


def extract_zones(settings, text_run: Run, encoder, batch_images: int = 4, workers: int = 4,
                  limit: int | None = None, say=print, resume: bool = True) -> Run:
    """Encode les 20 zones de chaque œuvre déjà vue par SigLIP 2 (``text_run``). Reprend un
    run inachevé s'il existe (mêmes œuvres)."""
    from ..catalog import db
    from ..catalog.ingest import thumb_path

    src = Path(text_run.path)
    keep = np.load(src / "status.npy") == OK
    ids = np.load(src / "ids.npy")[keep]
    if limit:
        ids = ids[:limit]
    boxes = zone_boxes()
    Z = len(boxes)

    run = find_zone_run(settings.runs_dir) if resume else None
    if run is not None and (run.manifest.get("status") == "complete"
                            or not np.array_equal(np.load(run.path / "ids.npy"), ids)):
        run = None
    if run is None:
        run = create_run("features", f"zones_{encoder.name}",
                         {"encoder": encoder.name, "weights": getattr(encoder, "weights", None),
                          "input_size": encoder.input_size, "grids": list(GRIDS), "zones": Z,
                          "image_source": "vignettes 1024 px", "limit": limit}, parent=text_run,
                         runs_dir=settings.runs_dir)
        np.save(run.path / "ids.npy", ids)
        np.lib.format.open_memmap(run.path / "zones.npy", mode="w+", dtype=np.float16,
                                  shape=(len(ids), Z, encoder.dim)).flush()
        np.save(run.path / "done.npy", np.zeros(len(ids), dtype=bool))
        say(f"Nouveau run {run.id} : {len(ids)} œuvres × {Z} zones")
    else:
        say(f"Reprise de {run.id}")
    zones = np.load(run.path / "zones.npy", mmap_mode="r+")
    done = np.load(run.path / "done.npy")
    todo = np.flatnonzero(~done)
    say(f"{len(todo)} œuvres à traiter ({int(done.sum())} déjà faites)")

    conn = db.connect(settings.catalog_path)
    paths = dict(conn.execute("SELECT id, path FROM artworks").fetchall())
    conn.close()

    def prepare(row: int):
        aid = int(ids[row])
        p = thumb_path(settings.thumbs_dir, aid, 1024)
        if not p.exists():
            p = Path(paths.get(aid, ""))
        try:
            im = open_image(p, target=1024)
        except Exception:  # image illisible : zones nulles, l'œuvre est marquée faite
            return row, None
        return row, np.stack([encoder.preprocess(c)[0] for c in crops(im, boxes)])

    t0, last_save, n_done = time.time(), time.time(), 0
    try:
        with ThreadPoolExecutor(workers) as pool:
            for s in range(0, len(todo), 256):
                chunk = todo[s:s + 256]
                prepared = pool.map(prepare, chunk)
                buf_rows, buf = [], []
                for row, arr in prepared:
                    if arr is None:
                        done[row] = True
                        continue
                    buf_rows.append(row)
                    buf.append(arr)
                    if len(buf) == batch_images:
                        _encode_into(encoder, zones, buf_rows, buf, Z)
                        done[buf_rows] = True
                        n_done += len(buf_rows)
                        buf_rows, buf = [], []
                if buf:
                    _encode_into(encoder, zones, buf_rows, buf, Z)
                    done[buf_rows] = True
                    n_done += len(buf_rows)
                if time.time() - last_save > 60 or s + 256 >= len(todo):
                    zones.flush()
                    np.save(run.path / "done.npy", done)
                    last_save = time.time()
                    rate = n_done / max(time.time() - t0, 1e-6)
                    left = (len(todo) - s - len(chunk)) / max(rate, 1e-6)
                    say(f"  {int(done.sum())}/{len(ids)} œuvres · {rate * Z:.0f} zones/s · reste ≈ {left / 3600:.1f} h")
    except BaseException as exc:
        zones.flush()
        np.save(run.path / "done.npy", done)
        run.fail(exc)
        raise
    zones.flush()
    np.save(run.path / "done.npy", done)
    run.complete(artworks=int(done.sum()), zones=int(done.sum()) * Z,
                 zones_per_second=round(n_done * Z / max(time.time() - t0, 1e-6), 1))
    return run


def _encode_into(encoder, zones, rows, arrays, Z):
    batch = np.concatenate(arrays)                       # (len(rows) * Z, 3, S, S)
    vecs = encoder.encode(batch).global_vectors.astype(np.float16)
    for k, row in enumerate(rows):
        zones[row] = vecs[k * Z:(k + 1) * Z]


# ------------------------------------------------------------------ index
def build_zone_index(zone_run: Run, runs_dir: Path | None = None, pca_dim: int = PCA_DIM, say=print) -> Run:
    import faiss
    from sklearn.decomposition import PCA

    p = Path(zone_run.path)
    ids = np.load(p / "ids.npy")
    done = np.load(p / "done.npy")
    Zs = np.load(p / "zones.npy", mmap_mode="r")
    rows = np.flatnonzero(done)
    Z = Zs.shape[1]
    rng = np.random.default_rng(SEED)
    sample_rows = rng.choice(rows, min(len(rows), 20_000), replace=False)
    sample = np.asarray(Zs[np.sort(sample_rows)], dtype=np.float32).reshape(-1, Zs.shape[2])
    sample = sample[np.linalg.norm(sample, axis=1) > 1e-3]
    say(f"PCA {pca_dim} sur {len(sample)} zones…")
    pca = PCA(n_components=min(pca_dim, sample.shape[1]), random_state=SEED).fit(sample)
    mean, comps = pca.mean_.astype(np.float32), pca.components_.astype(np.float32)
    explained = float(pca.explained_variance_ratio_.sum())

    d = comps.shape[0]
    index = faiss.IndexScalarQuantizer(d, faiss.ScalarQuantizer.QT_fp16, faiss.METRIC_INNER_PRODUCT)
    zone_ids, zone_cells, zone_rows = [], [], []
    for s in range(0, len(rows), 4096):
        r = rows[s:s + 4096]
        block = np.asarray(Zs[r], dtype=np.float32)       # (b, Z, D)
        norms = np.linalg.norm(block, axis=2)
        bi, ci = np.nonzero(norms > 1e-3)
        index.add(((block[bi, ci] - mean) @ comps.T).astype(np.float32))
        zone_ids.append(ids[r][bi])
        zone_cells.append(ci.astype(np.int16))
        zone_rows.append(r[bi].astype(np.int64))
    run = create_run("index", f"textzones_{zone_run.manifest['params']['encoder']}",
                     {"kind": "flat fp16", "pca_dim": d, "grids": zone_run.manifest["params"]["grids"],
                      "explained_variance": round(explained, 4)}, parent=zone_run, runs_dir=runs_dir)
    faiss.write_index(index, str(run.path / "zones.faiss"))
    np.save(run.path / "zone_ids.npy", np.concatenate(zone_ids).astype(np.int64))
    np.save(run.path / "zone_cells.npy", np.concatenate(zone_cells))
    np.save(run.path / "zone_rows.npy", np.concatenate(zone_rows))
    np.save(run.path / "pca_mean.npy", mean)
    np.save(run.path / "pca_components.npy", comps)
    run.complete(count=int(index.ntotal), artworks=int(len(rows)), explained_variance=round(explained, 4))
    say(f"Index : {index.ntotal} zones de {len(rows)} œuvres ({explained:.0%} de la variance gardée) → {run.id}")
    return run


def find_zone_index(runs_dir: Path | None) -> Run | None:
    runs = [r for r in list_runs("index", runs_dir=runs_dir)
            if r.manifest["name"].startswith("textzones_") and r.manifest.get("status") == "complete"]
    return runs[-1] if runs else None


class ZoneIndex:
    def __init__(self, run: Run):
        import faiss

        p = Path(run.path)
        self.run = run
        self.index = faiss.read_index(str(p / "zones.faiss"))
        self.zone_ids = np.load(p / "zone_ids.npy")
        self.zone_cells = np.load(p / "zone_cells.npy")
        self.mean = np.load(p / "pca_mean.npy")
        self.comps = np.load(p / "pca_components.npy")
        self.boxes = zone_boxes(tuple(run.manifest["params"].get("grids", GRIDS)))
        # vecteurs d'origine (float16, sur disque) pour reclasser exactement les candidates
        self.zone_rows = np.load(p / "zone_rows.npy") if (p / "zone_rows.npy").exists() else None
        parent = Path(run.path).parents[1] / run.manifest.get("parent", "")
        self.full = np.load(parent / "zones.npy", mmap_mode="r") if (parent / "zones.npy").exists() else None

    def search(self, text_vector: np.ndarray, k: int = 60, allowed=None) -> list[dict]:
        """Les k œuvres dont une zone répond le mieux à la phrase (une zone par œuvre)."""
        v = np.asarray(text_vector, dtype=np.float32)
        q = (v @ self.comps.T)[None].astype(np.float32)
        scores, rows = self.index.search(q, k * 8)
        pairs = [(float(s), int(r)) for s, r in zip(scores[0], rows[0]) if r >= 0]
        if self.full is not None and self.zone_rows is not None and pairs:
            # reclassement exact : similarité cosinus avec le vecteur d'origine de chaque zone
            idx = np.array([r for _, r in pairs])
            order = np.argsort(self.zone_rows[idx], kind="stable")
            vecs = np.empty((len(idx), self.full.shape[2]), dtype=np.float32)
            vecs[order] = np.asarray(self.full[self.zone_rows[idx][order], self.zone_cells[idx][order].astype(np.int64)],
                                     dtype=np.float32)
            exact = vecs @ v
            pairs = sorted(zip(exact.tolist(), idx.tolist()), reverse=True)
        out, seen = [], set()
        for s, r in pairs:
            aid = int(self.zone_ids[r])
            if aid in seen or (allowed is not None and aid not in allowed):
                continue
            seen.add(aid)
            g, box = self.boxes[int(self.zone_cells[r])]
            out.append({"id": aid, "score": round(float(s), 4), "grid": g, "box": list(box)})
            if len(out) >= k:
                break
        return out


def write_log(run: Run, text: str) -> None:
    with open(Path(run.path) / "progress.log", "a", encoding="utf-8") as f:
        f.write(text + "\n")
