"""« Pourquoi ces deux œuvres se ressemblent ? » — les zones qui se répondent.

Pour un regard qui garde des vecteurs par zone (``regions.npy`` : DINOv3, la forme), chaque œuvre
est découpée en 16 cases (grille 4 × 4 du carré où l'œuvre a été posée, sans recadrage). On retire
d'abord à chaque case sa moyenne sur le corpus (une moyenne par position 0..15, pour effacer la
signature de position et de bord de DINOv3), puis on cherche les **correspondances mutuelles** : la
case b est la plus proche de a parmi les cases de B, et a la plus proche de b parmi celles de A.
Quand les vecteurs globaux des deux œuvres sont fournis, on classe ces correspondances par leur
ressemblance centrée pondérée par l'alignement de chaque case avec le vecteur global de son œuvre,
afin de mettre en tête les zones qui pèsent réellement dans la ressemblance globale.

Le calcul est immédiat (16 × 16 cosinus) : la moyenne par case est calculée une seule fois par run
de vecteurs et mise en cache dans ``cell_means_4x4.npy``. Ce sont des pistes pour regarder, pas une
explication du modèle : un regard compare des formes, pas des sujets ni des intentions.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from ..features.extract import OK
from ..features.regions import DEFAULT_GRIDS
from ..index.regions import cell_boxes, square_to_image

GRID = 4
CELL_MEANS_FILE = "cell_means_4x4.npy"


def cells_of(regions: np.ndarray, grids: tuple[int, ...] = DEFAULT_GRIDS) -> np.ndarray:
    """(R, D) → (16, D) : les cases 4 × 4, dans l'ordre ligne par ligne."""
    start = sum(g * g for g in grids if g < GRID)
    if GRID not in grids:
        raise ValueError(f"Pas de grille {GRID} × {GRID} dans {grids}")
    return np.asarray(regions[start:start + GRID * GRID], dtype=np.float32)


def compute_cell_means(
    regions_path: Path,
    status_path: Path,
    grids: tuple[int, ...] = DEFAULT_GRIDS,
    chunk: int = 4096,
) -> np.ndarray:
    """Calcule la moyenne sur le corpus de chaque case 4 × 4 (vecteurs normalisés L2 par case).

    Renvoie un tableau ``(16, D)`` float32 ; seules les œuvres ``OK`` et les cases de norme non
    nulle contribuent à la moyenne de leur position.
    """
    start = sum(g * g for g in grids if g < GRID)
    if GRID not in grids:
        raise ValueError(f"Pas de grille {GRID} × {GRID} dans {grids}")
    R = np.load(regions_path, mmap_mode="r")
    status = np.load(status_path)
    n_items, _, dim = R.shape
    sums = np.zeros((GRID * GRID, dim), dtype=np.float64)
    counts = np.zeros(GRID * GRID, dtype=np.int64)
    for s in range(0, n_items, chunk):
        ok = np.flatnonzero(status[s:s + chunk] == OK)
        if not len(ok):
            continue
        blk = np.asarray(R[s:s + chunk][ok, start:start + GRID * GRID, :], dtype=np.float32)
        norms = np.linalg.norm(blk, axis=2)
        valid = norms > 1e-6
        blk_n = blk / np.maximum(norms[:, :, None], 1e-6)
        blk_n[~valid] = 0.0
        sums += blk_n.sum(axis=0, dtype=np.float64)
        counts += valid.sum(axis=0)
    return (sums / np.maximum(counts[:, None], 1)).astype(np.float32)


def load_or_compute_cell_means(
    run_path: Path,
    grids: tuple[int, ...] = DEFAULT_GRIDS,
) -> np.ndarray | None:
    """Charge ``cell_means_4x4.npy`` depuis le dossier du run de vecteurs, ou le calcule et le met en cache."""
    regions_path = Path(run_path) / "regions.npy"
    status_path = Path(run_path) / "status.npy"
    if not regions_path.exists() or not status_path.exists():
        return None
    cache = Path(run_path) / CELL_MEANS_FILE
    R = np.load(regions_path, mmap_mode="r")
    expected = (GRID * GRID, R.shape[2])
    if cache.exists():
        try:
            arr = np.load(cache)
            if arr.shape == expected and np.isfinite(arr).all():
                return np.asarray(arr, dtype=np.float32)
        except Exception:
            pass
    means = compute_cell_means(regions_path, status_path, grids=grids)
    tmp = cache.with_suffix(f".tmp.{os.getpid()}.npy")
    try:
        np.save(tmp, means)
        os.replace(tmp, cache)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
    return means


def match(
    cells_a: np.ndarray,
    cells_b: np.ndarray,
    boxes_a: list,
    boxes_b: list,
    k: int = 4,
    *,
    cell_means: np.ndarray | None = None,
    global_a: np.ndarray | None = None,
    global_b: np.ndarray | None = None,
) -> list[dict]:
    """Correspondances mutuelles entre les cases de A et de B (cases hors de l'œuvre exclues).

    ``boxes_*`` : cadre de chaque case sur l'œuvre (fractions de l'image) ou None si la case tombe
    entièrement dans les bandes ajoutées pour mettre l'œuvre au carré.
    Si ``cell_means`` ``(16, D)`` est fourni, chaque case normalisée est centrée par sa moyenne sur
    le corpus avant le calcul des cosinus. Si ``global_a`` et ``global_b`` sont fournis, les
    correspondances mutuelles sont classées par ``max(0, sim) * max(0, align_a) * max(0, align_b)``
    (sinon par ``lift`` décroissant).
    """
    norms_a = np.linalg.norm(cells_a, axis=1)
    norms_b = np.linalg.norm(cells_b, axis=1)
    va = np.array([b is not None for b in boxes_a], dtype=bool) & (norms_a > 1e-6)
    vb = np.array([b is not None for b in boxes_b], dtype=bool) & (norms_b > 1e-6)
    if k <= 0 or not va.any() or not vb.any():
        return []

    A_raw = cells_a / np.maximum(norms_a[:, None], 1e-6)
    B_raw = cells_b / np.maximum(norms_b[:, None], 1e-6)
    if cell_means is not None:
        Ac = A_raw - np.asarray(cell_means, dtype=np.float32)
        Bc = B_raw - np.asarray(cell_means, dtype=np.float32)
        A = Ac / np.maximum(np.linalg.norm(Ac, axis=1, keepdims=True), 1e-6)
        B = Bc / np.maximum(np.linalg.norm(Bc, axis=1, keepdims=True), 1e-6)
    else:
        A, B = A_raw, B_raw

    S = A @ B.T
    # Sommes et effectifs sur les seules cases valides (sans nanmean : pas d'avertissement quand
    # une œuvre non carrée laisse des rangées entières hors de l'œuvre).
    V = np.where(va[:, None] & vb[None, :], S, 0.0)
    row_sum, col_sum = V.sum(axis=1), V.sum(axis=0)
    n_b, n_a = int(vb.sum()), int(va.sum())
    S_m = S.copy()
    S_m[~va, :] = -np.inf
    S_m[:, ~vb] = -np.inf
    best_b, best_a = S_m.argmax(axis=1), S_m.argmax(axis=0)

    use_align = global_a is not None and global_b is not None
    if use_align:
        ga = np.asarray(global_a, dtype=np.float32)
        gb = np.asarray(global_b, dtype=np.float32)
        ga = ga / max(float(np.linalg.norm(ga)), 1e-12)
        gb = gb / max(float(np.linalg.norm(gb)), 1e-12)
        align_a = A_raw @ ga
        align_b = B_raw @ gb
    else:
        align_a = align_b = None

    out = []
    for i in np.flatnonzero(va):
        j = int(best_b[i])
        if best_a[j] != i:
            continue                                   # pas mutuelle
        sim = float(S[i, j])
        # ressemblance moyenne de chaque case avec TOUTES LES AUTRES cases de l'autre œuvre
        # (la paire elle-même exclue, comme le dit la documentation) ; sans autre case : 0
        others = [(row_sum[i] - sim) / (n_b - 1)] if n_b > 1 else []
        others += [(col_sum[j] - sim) / (n_a - 1)] if n_a > 1 else []
        lift = float(sim - max(others)) if others else 0.0
        item = {"cell_a": int(i), "cell_b": j, "box_a": boxes_a[i], "box_b": boxes_b[j],
                "sim": round(sim, 4), "lift": round(lift, 4)}
        if use_align:
            al_a = max(0.0, float(align_a[i]))
            al_b = max(0.0, float(align_b[j]))
            item["_rank"] = max(0.0, sim) * al_a * al_b
        else:
            item["_rank"] = lift
        out.append(item)
    out.sort(key=lambda m: (-m["_rank"], -m["sim"]))
    for m in out:
        m.pop("_rank", None)
    return out[:k]


def correspondences(
    regions_a: np.ndarray,
    regions_b: np.ndarray,
    size_a: tuple[int, int],
    size_b: tuple[int, int],
    grids: tuple[int, ...] = DEFAULT_GRIDS,
    k: int = 4,
    patches: int | None = None,
    *,
    cell_means: np.ndarray | None = None,
    global_a: np.ndarray | None = None,
    global_b: np.ndarray | None = None,
) -> list[dict]:
    """Zones qui se répondent entre deux œuvres, avec leurs cadres sur chaque image. ``patches`` :
    patchs par côté du modèle, pour que les cadres suivent le découpage réel des patchs."""
    squares = [box for g, box in cell_boxes((GRID,), patches)]
    boxes_a = [square_to_image(b, *size_a) for b in squares]
    boxes_b = [square_to_image(b, *size_b) for b in squares]
    return match(
        cells_of(regions_a, grids),
        cells_of(regions_b, grids),
        boxes_a,
        boxes_b,
        k=k,
        cell_means=cell_means,
        global_a=global_a,
        global_b=global_b,
    )
