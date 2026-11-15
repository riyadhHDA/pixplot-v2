"""Lecture d'un run de vecteurs et recherche d'images similaires.

Recherche exacte par produit scalaire, par blocs depuis le disque : suffisant pour
valider l'étape 1 (et utilisable jusqu'à quelques centaines de milliers d'œuvres).
L'index FAISS arrivera à l'étape 2.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..runs import Run
from .extract import OK


@dataclass
class FeatureStore:
    run: Run
    ids: np.ndarray
    global_vectors: np.ndarray  # memmap float16 (N, D)
    status: np.ndarray

    @classmethod
    def open(cls, run: Run) -> "FeatureStore":
        p = Path(run.path)
        return cls(
            run=run,
            ids=np.load(p / "ids.npy"),
            global_vectors=np.load(p / "global.npy", mmap_mode="r"),
            status=np.load(p / "status.npy"),
        )

    def row_of(self, artwork_id: int) -> int:
        rows = np.flatnonzero(self.ids == artwork_id)
        if not len(rows):
            raise KeyError(f"L'œuvre {artwork_id} n'est pas dans ce run ({self.run.id})")
        if self.status[rows[0]] != OK:
            raise KeyError(f"L'œuvre {artwork_id} n'a pas de vecteur valide dans ce run")
        return int(rows[0])

    def search(self, query: np.ndarray, k: int = 10, exclude_row: int | None = None,
               block: int = 65536) -> list[tuple[int, float]]:
        """Les ``k`` œuvres les plus proches d'un vecteur normalisé. Renvoie (artwork_id, score)."""
        q = np.asarray(query, dtype=np.float32)
        n = len(self.ids)
        scores = np.empty(n, dtype=np.float32)
        for s in range(0, n, block):
            scores[s:s + block] = self.global_vectors[s:s + block].astype(np.float32) @ q
        scores[self.status != OK] = -np.inf
        if exclude_row is not None:
            scores[exclude_row] = -np.inf
        k = min(k, int(np.isfinite(scores).sum()))
        if k <= 0:
            return []
        top = np.argpartition(-scores, k - 1)[:k]
        top = top[np.argsort(-scores[top])]
        return [(int(self.ids[r]), float(scores[r])) for r in top]

    def similar(self, artwork_id: int, k: int = 10) -> list[tuple[int, float]]:
        row = self.row_of(artwork_id)
        return self.search(self.global_vectors[row], k=k, exclude_row=row)
