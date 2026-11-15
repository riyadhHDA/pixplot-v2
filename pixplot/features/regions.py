"""Vecteurs régionaux : résumer la grille de patchs en quelques régions par œuvre.

Garder tous les patchs DINOv3 de 500 000 œuvres coûterait ~150 Go. On les moyenne
sur des grilles 1×1, 2×2 et 4×4 (21 régions), ce qui suffit pour la recherche par
détail et tient en quelques Go (puis ~0,5 Go une fois compressé par FAISS IVF-PQ).
"""

from __future__ import annotations

import numpy as np

DEFAULT_GRIDS = (1, 2, 4)


def region_count(grids: tuple[int, ...] = DEFAULT_GRIDS) -> int:
    return sum(g * g for g in grids)


def pool_regions(
    patch_grid: np.ndarray,
    grids: tuple[int, ...] = DEFAULT_GRIDS,
    mask: np.ndarray | None = None,
) -> np.ndarray:
    """Moyenne les patchs par région.

    patch_grid : (N, gh, gw, D)
    mask       : (N, gh, gw) booléen, True = patch sur l'œuvre (False = bande de letterbox).
                 Les bandes sont ignorées dans les moyennes.
    Retour     : (N, R, D) float32 normalisé L2, R = somme des g² (21 par défaut).
                 Ordre : grille par grille, puis ligne par ligne.
    """
    n, gh, gw, d = patch_grid.shape
    if mask is None:
        mask = np.ones((n, gh, gw), dtype=bool)
    weights = mask.astype(np.float32)[..., None]

    out = np.empty((n, region_count(grids), d), dtype=np.float32)
    k = 0
    for g in grids:
        rows = np.array_split(np.arange(gh), g)
        cols = np.array_split(np.arange(gw), g)
        for r in rows:
            for c in cols:
                block = patch_grid[:, r[:, None], c[None, :], :]
                w = weights[:, r[:, None], c[None, :], :]
                total = w.sum(axis=(1, 2))
                mean = (block * w).sum(axis=(1, 2)) / np.maximum(total, 1.0)
                out[:, k] = mean
                k += 1

    norms = np.linalg.norm(out, axis=-1, keepdims=True)
    return out / np.maximum(norms, 1e-12)


def letterbox_mask(content_box: tuple[int, int, int, int], input_size: int, patch_size: int) -> np.ndarray:
    """Masque (gh, gw) des patchs dont le centre tombe sur l'œuvre et non sur une bande."""
    left, top, w, h = content_box
    g = input_size // patch_size
    centers = (np.arange(g) + 0.5) * patch_size
    in_x = (centers >= left) & (centers < left + w)
    in_y = (centers >= top) & (centers < top + h)
    return in_y[:, None] & in_x[None, :]
