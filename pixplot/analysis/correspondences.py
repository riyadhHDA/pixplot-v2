"""« Pourquoi ces deux œuvres se ressemblent ? » — les zones qui se répondent.

Pour un regard qui garde des vecteurs par zone (``regions.npy`` : DINOv3, la forme), chaque œuvre
est découpée en 16 cases (grille 4 × 4 du carré où l'œuvre a été posée, sans recadrage). On compare
chaque case de l'œuvre A à chaque case de l'œuvre B (cosinus) et on garde les **correspondances
mutuelles** : la case b est la plus proche de a parmi les cases de B, et a la plus proche de b parmi
celles de A. Elles sont classées par ce qui les distingue (cosinus au-dessus de la ressemblance
moyenne des deux cases avec toutes les autres), pour ne pas mettre en tête deux ciels quelconques.

Le calcul est immédiat (16 × 16 cosinus) : rien n'est précalculé. Ce sont des pistes pour regarder,
pas une explication du modèle : un regard compare des formes, pas des sujets ni des intentions.
"""

from __future__ import annotations

import numpy as np

from ..features.regions import DEFAULT_GRIDS
from ..index.regions import cell_boxes, square_to_image

GRID = 4


def cells_of(regions: np.ndarray, grids: tuple[int, ...] = DEFAULT_GRIDS) -> np.ndarray:
    """(R, D) → (16, D) : les cases 4 × 4, dans l'ordre ligne par ligne."""
    start = sum(g * g for g in grids if g < GRID)
    if GRID not in grids:
        raise ValueError(f"Pas de grille {GRID} × {GRID} dans {grids}")
    return np.asarray(regions[start:start + GRID * GRID], dtype=np.float32)


def match(cells_a: np.ndarray, cells_b: np.ndarray, boxes_a: list, boxes_b: list, k: int = 4) -> list[dict]:
    """Correspondances mutuelles entre les cases de A et de B (cases hors de l'œuvre exclues).

    ``boxes_*`` : cadre de chaque case sur l'œuvre (fractions de l'image) ou None si la case tombe
    entièrement dans les bandes ajoutées pour mettre l'œuvre au carré."""
    A = cells_a / np.maximum(np.linalg.norm(cells_a, axis=1, keepdims=True), 1e-6)
    B = cells_b / np.maximum(np.linalg.norm(cells_b, axis=1, keepdims=True), 1e-6)
    S = A @ B.T
    va = np.array([b is not None for b in boxes_a], dtype=bool) & (np.linalg.norm(cells_a, axis=1) > 1e-6)
    vb = np.array([b is not None for b in boxes_b], dtype=bool) & (np.linalg.norm(cells_b, axis=1) > 1e-6)
    if k <= 0 or not va.any() or not vb.any():
        return []
    # Sommes et effectifs sur les seules cases valides (sans nanmean : pas d'avertissement quand
    # une œuvre non carrée laisse des rangées entières hors de l'œuvre).
    V = np.where(va[:, None] & vb[None, :], S, 0.0)
    row_sum, col_sum = V.sum(axis=1), V.sum(axis=0)
    n_b, n_a = int(vb.sum()), int(va.sum())
    S[~va, :] = -np.inf
    S[:, ~vb] = -np.inf
    best_b, best_a = S.argmax(axis=1), S.argmax(axis=0)
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
        out.append({"cell_a": int(i), "cell_b": j, "box_a": boxes_a[i], "box_b": boxes_b[j],
                    "sim": round(sim, 4), "lift": round(lift, 4)})
    out.sort(key=lambda m: (-m["lift"], -m["sim"]))
    return out[:k]


def correspondences(regions_a: np.ndarray, regions_b: np.ndarray, size_a: tuple[int, int],
                    size_b: tuple[int, int], grids: tuple[int, ...] = DEFAULT_GRIDS, k: int = 4) -> list[dict]:
    """Zones qui se répondent entre deux œuvres, avec leurs cadres sur chaque image."""
    squares = [box for g, box in cell_boxes((GRID,))]
    boxes_a = [square_to_image(b, *size_a) for b in squares]
    boxes_b = [square_to_image(b, *size_b) for b in squares]
    return match(cells_of(regions_a, grids), cells_of(regions_b, grids), boxes_a, boxes_b, k=k)
