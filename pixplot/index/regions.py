"""Recherche par détail : index des zones d'œuvres et requête à partir d'un cadre.

Chaque œuvre a 21 vecteurs régionaux (grilles 1×1, 2×2, 4×4 : moyenne des patchs DINOv3
de la zone). On indexe les zones des grilles 2×2 et 4×4 (l'œuvre entière est déjà
couverte par l'index global), après réduction PCA à 256 dimensions.

Requête : l'historien trace un cadre sur une œuvre (une main, un drapé…). Le cadre est
découpé dans l'image originale et passé dans le même modèle, à une résolution qui
respecte son échelle dans l'œuvre ; la moyenne de ses patchs est comparée aux zones.

Contenu d'un run ``index/regions_<encodeur>_<horodatage>/`` :
    regions.faiss        index (exact, ou IVF-PQ au-delà de 1,5 million de zones)
    region_ids.npy       zone → identifiant de l'œuvre
    region_cells.npy     zone → numéro de la zone (0 à 20)
    pca_mean.npy, pca_components.npy   la réduction PCA, pour transformer les requêtes
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..encoders.base import Encoder, letterbox_box
from ..features.extract import OK
from ..features.regions import DEFAULT_GRIDS, letterbox_mask, pool_regions
from ..imageio import open_image
from ..runs import Run, create_run, list_runs

FLAT_LIMIT = 1_500_000
SEED = 42


def _bounds(g: int, patches: int | None) -> list[tuple[float, float]]:
    """Bornes des g bandes d'une grille, en fractions du carré. Avec ``patches`` (patchs par côté),
    ce sont celles du découpage réel des patchs (``np.array_split`` dans ``pool_regions``) : si le
    nombre de patchs n'est pas multiple de g (14 patchs en 4 → 4 + 4 + 3 + 3), les cadres suivent."""
    if not patches or patches % g == 0:
        return [(k / g, (k + 1) / g) for k in range(g)]
    parts = np.array_split(np.arange(patches), g)
    return [(int(r[0]) / patches, (int(r[-1]) + 1) / patches) for r in parts]


def patches_per_side(params: dict) -> int | None:
    """Nombre de patchs par côté d'un run de vecteurs (None si inconnu)."""
    size, patch = params.get("input_size"), params.get("patch_size")
    return int(size) // int(patch) if size and patch else None


def cell_boxes(grids: tuple[int, ...] = DEFAULT_GRIDS,
               patches: int | None = None) -> list[tuple[int, tuple[float, float, float, float]]]:
    """Pour chaque zone, (taille de grille, cadre [x0, y0, x1, y1] dans le carré letterbox)."""
    out = []
    for g in grids:
        b = _bounds(g, patches)
        for gy in range(g):
            for gx in range(g):
                out.append((g, (b[gx][0], b[gy][0], b[gx][1], b[gy][1])))
    return out


def square_to_image(box, width: int, height: int):
    """Cadre dans le carré letterbox → cadre en fractions de l'image (rogné à l'œuvre)."""
    a = width / max(height, 1)
    if a >= 1:
        cx0, cy0, cx1, cy1 = 0.0, (1 - 1 / a) / 2, 1.0, (1 + 1 / a) / 2
    else:
        cx0, cy0, cx1, cy1 = (1 - a) / 2, 0.0, (1 + a) / 2, 1.0
    x0, y0, x1, y1 = box
    x0, x1 = max(x0, cx0), min(x1, cx1)
    y0, y1 = max(y0, cy0), min(y1, cy1)
    if x1 <= x0 or y1 <= y0:
        return None
    return [round((x0 - cx0) / (cx1 - cx0), 4), round((y0 - cy0) / (cy1 - cy0), 4),
            round((x1 - cx0) / (cx1 - cx0), 4), round((y1 - cy0) / (cy1 - cy0), 4)]


def _faiss():
    import faiss
    return faiss


def build_region_index(features: Run, pca_dim: int = 256, runs_dir: Path | None = None,
                       block: int = 200_000) -> Run:
    faiss = _faiss()
    p = Path(features.path)
    if not (p / "regions.npy").exists():
        raise RuntimeError(f"{features.id} n'a pas de vecteurs régionaux (encodeur sans patchs ?)")
    grids = tuple(features.manifest["params"].get("region_grids", DEFAULT_GRIDS))
    patches = patches_per_side(features.manifest["params"])
    cells = cell_boxes(grids, patches)
    keep_cells = np.array([k for k, (g, _) in enumerate(cells) if g > 1])
    ids = np.load(p / "ids.npy")
    status = np.load(p / "status.npy")
    R = np.load(p / "regions.npy", mmap_mode="r")
    rows = np.flatnonzero(status == OK)
    dim = R.shape[2]
    pca_dim = min(pca_dim, dim)

    # Zones valides (une zone entièrement dans les bandes du letterbox vaut 0 : on l'écarte).
    region_ids, region_cells, sample = [], [], []
    rng = np.random.default_rng(SEED)
    for s in range(0, len(rows), 4096):
        chunk = np.asarray(R[rows[s:s + 4096]][:, keep_cells], dtype=np.float32)
        norms = np.linalg.norm(chunk, axis=2)
        r_idx, c_idx = np.nonzero(norms > 1e-3)
        region_ids.append(ids[rows[s:s + 4096]][r_idx])
        region_cells.append(keep_cells[c_idx])
        if len(r_idx):
            take = rng.choice(len(r_idx), min(len(r_idx), max(1, 200_000 * len(rows[s:s + 4096]) // max(len(rows), 1))), replace=False)
            sample.append(chunk[r_idx[take], c_idx[take]])
    if not region_ids or not sample:
        raise RuntimeError("Aucune zone à indexer (aucune œuvre traitée dans ce run)")
    region_ids = np.concatenate(region_ids).astype(np.int64)
    region_cells = np.concatenate(region_cells).astype(np.int16)
    sample = np.concatenate(sample)

    from sklearn.decomposition import PCA
    pca = PCA(n_components=min(pca_dim, len(sample) - 1, dim), random_state=SEED).fit(sample)
    mean, comps = pca.mean_.astype(np.float32), pca.components_.astype(np.float32)

    def transform(x):
        z = (x - mean) @ comps.T
        return (z / np.maximum(np.linalg.norm(z, axis=1, keepdims=True), 1e-12)).astype(np.float32)

    n = len(region_ids)
    d = comps.shape[0]
    if n <= FLAT_LIMIT:
        index, kind = faiss.IndexFlatIP(d), "flat"
    else:
        nlist = int(4 * np.sqrt(n))
        index = faiss.IndexIVFPQ(faiss.IndexFlatIP(d), d, nlist, 32, 8, faiss.METRIC_INNER_PRODUCT)
        index.train(transform(sample))
        kind = f"ivfpq(nlist={nlist},m=32)"

    run = create_run("index", f"regions_{features.manifest['name']}",
                     {"kind": kind, "pca_dim": d, "grids": list(grids), "patches": patches,
                      "cells_indexed": keep_cells.tolist()},
                     parent=features, runs_dir=runs_dir)
    try:
        # Même ordre de parcours qu'à la collecte : les vecteurs s'alignent sur region_ids.
        for s in range(0, len(rows), 4096):
            chunk = np.asarray(R[rows[s:s + 4096]][:, keep_cells], dtype=np.float32)
            norms = np.linalg.norm(chunk, axis=2)
            r_idx, c_idx = np.nonzero(norms > 1e-3)
            if len(r_idx):
                index.add(transform(chunk[r_idx, c_idx]))
        faiss.write_index(index, str(run.path / "regions.faiss"))
        np.save(run.path / "region_ids.npy", region_ids)
        np.save(run.path / "region_cells.npy", region_cells)
        np.save(run.path / "pca_mean.npy", mean)
        np.save(run.path / "pca_components.npy", comps)
    except BaseException as exc:
        run.fail(exc)
        raise
    run.complete(count=int(index.ntotal), artworks=int(len(np.unique(region_ids))))
    return run


def find_region_index(features: Run, runs_dir: Path | None = None) -> Run | None:
    for run in reversed(list_runs("index", runs_dir=runs_dir)):
        if run.manifest.get("parent") == features.id and run.manifest["name"].startswith("regions_"):
            return run
    return None


SIZE_BUCKETS = (112, 224, 336, 448)  # multiples de 16 (DINOv3) et de 14 (DINOv2)


def choose_size(ideal: float, full: int, patch: int) -> int:
    """Résolution de la requête, arrondie à quelques tailles fixes : sur GPU AMD, chaque
    nouvelle taille d'image déclenche une compilation (~20 s) ; avec 4 tailles, elle n'a
    lieu qu'une fois par taille."""
    buckets = [b for b in SIZE_BUCKETS if b <= full and b % patch == 0] or [full]
    return min(buckets, key=lambda b: abs(b - ideal))


def encode_box(encoder: Encoder, image_path: Path, box: tuple[float, float, float, float]) -> np.ndarray:
    """Vecteur d'un cadre tracé sur une œuvre (fractions [x0, y0, x1, y1] de l'image)."""
    x0, y0, x1, y1 = [min(max(float(v), 0.0), 1.0) for v in box]
    if x1 - x0 < 0.02 or y1 - y0 < 0.02:
        raise ValueError("Cadre trop petit")
    im = open_image(image_path, target=2048)
    w, h = im.size
    crop = im.crop((int(x0 * w), int(y0 * h), max(int(x1 * w), int(x0 * w) + 1), max(int(y1 * h), int(y0 * h) + 1)))
    # Résolution proportionnelle à la taille du cadre dans l'œuvre : un détail est vu à la
    # même échelle que lorsque l'œuvre entière a été analysée.
    ps = encoder.patch_size or 16
    full = encoder.input_size
    size = choose_size(full * max(x1 - x0, y1 - y0), full, ps)
    encoder.input_size = size
    try:
        arr, content = encoder.preprocess(crop)
        out = encoder.encode(arr[None])
    finally:
        encoder.input_size = full
    if out.patch_grid is None:
        raise RuntimeError("Cet encodeur ne fournit pas de patchs : recherche par détail impossible")
    mask = letterbox_mask(content, size, ps)[None]
    return pool_regions(out.patch_grid, grids=(1,), mask=mask)[0, 0]


@dataclass
class RegionIndex:
    run: Run
    index: object
    region_ids: np.ndarray
    region_cells: np.ndarray
    mean: np.ndarray
    comps: np.ndarray
    cells: list

    @classmethod
    def open(cls, run: Run) -> "RegionIndex":
        p = Path(run.path)
        index = _faiss().read_index(str(p / "regions.faiss"))
        if hasattr(index, "nprobe"):
            index.nprobe = 32
        grids = tuple(run.manifest["params"].get("grids", DEFAULT_GRIDS))
        patches = run.manifest["params"].get("patches")
        return cls(run, index, np.load(p / "region_ids.npy"), np.load(p / "region_cells.npy"),
                   np.load(p / "pca_mean.npy"), np.load(p / "pca_components.npy"), cell_boxes(grids, patches))

    def search(self, vector: np.ndarray, k: int = 30, exclude: int | None = None,
               allowed: set[int] | None = None) -> list[dict]:
        """Les k œuvres contenant la zone la plus proche (une seule zone par œuvre). ``allowed`` :
        ne garder que ces œuvres (celles de l'analyse affichée)."""
        z = (np.asarray(vector, dtype=np.float32) - self.mean) @ self.comps.T
        z = (z / max(np.linalg.norm(z), 1e-12)).astype(np.float32)[None]
        # 20 zones indexées par œuvre : en demander k × 20 garantit k œuvres distinctes
        scores, rows = self.index.search(z, min(self.index.ntotal, k * 20))
        out, seen = [], set()
        for score, r in zip(scores[0], rows[0]):
            if r < 0:
                continue
            aid = int(self.region_ids[r])
            if aid == exclude or aid in seen or (allowed is not None and aid not in allowed):
                continue
            seen.add(aid)
            g, square = self.cells[int(self.region_cells[r])]
            out.append({"id": aid, "score": round(float(score), 4), "cell": int(self.region_cells[r]),
                        "grid": g, "square_box": square})
            if len(out) >= k:
                break
        return out
