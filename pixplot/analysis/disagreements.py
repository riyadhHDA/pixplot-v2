"""Désaccords entre regards : deux œuvres qu'un regard rapproche et qu'un autre sépare.

Pour un historien, c'est souvent là que se trouve l'information : deux tableaux voisins
par la composition mais opposés par le sujet (une mise en page reprise pour un autre
thème), voisins par le sujet mais étrangers par la facture (le même thème traité par deux
mains), etc.

Méthode, pour chaque couple de regards (proche selon A, loin selon B) :

1. les ``k`` plus proches voisines de chaque œuvre selon A (calcul exact, FAISS) ;
2. pour chaque paire (œuvre, voisine), son **centile** selon B : la part du corpus plus
   éloignée de l'œuvre que la voisine, estimée sur un échantillon fixe de 2 048 œuvres
   (0,5 = distance banale, proche de 0 = parmi les plus lointaines) ;
3. on garde les paires très proches selon A (rang ≤ ``max_rank``) et loin selon B
   (centile < ``max_centile``), triées du désaccord le plus fort au plus faible.

Ce sont des pistes à regarder, pas des résultats : un désaccord peut venir d'une
reproduction de mauvaise qualité, d'un recadrage, d'une étiquette fausse… ou d'une vraie
parenté qu'un seul regard perçoit.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

FILE = "disagreements.json"
SAMPLE = 2048


def _knn(X: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    from .layout import neighbors

    return neighbors(X, k)


def centiles(XB: np.ndarray, rows_a: np.ndarray, rows_b: np.ndarray, sample: np.ndarray,
             chunk: int = 8192) -> np.ndarray:
    """Centile de la paire (a, b) dans le regard B : part de l'échantillon moins proche de
    ``a`` que ``b``. Vectorisé par blocs."""
    out = np.empty(len(rows_a), dtype=np.float32)
    S = XB[sample]                                            # (m, d)
    for s in range(0, len(rows_a), chunk):
        a, b = rows_a[s:s + chunk], rows_b[s:s + chunk]
        ref = XB[a] @ S.T                                     # (c, m)
        sab = np.einsum("ij,ij->i", XB[a], XB[b])[:, None]
        out[s:s + chunk] = (ref < sab).mean(axis=1)
    return out


def compute(vectors: dict[str, tuple[np.ndarray, dict[int, int]]], ids: list[int], k: int = 10,
            max_rank: int = 5, max_centile: float = 0.35, keep: int = 300, max_per_work: int = 2,
            seed: int = 0, say=print) -> dict:
    """``vectors`` : regard → (vecteurs normalisés, id → ligne). Seules les œuvres connues
    de tous les regards sont comparées (sinon un désaccord ne veut rien dire)."""
    common = [i for i in ids if all(i in row for _, row in vectors.values())]
    rng = np.random.default_rng(seed)
    sample_ids = rng.choice(len(common), size=min(SAMPLE, len(common)), replace=False)
    mats = {}
    for key, (X, row) in vectors.items():
        mats[key] = np.ascontiguousarray(X[[row[i] for i in common]])
    out = {"k": k, "max_rank": max_rank, "max_centile": max_centile, "max_per_work": max_per_work, "n": len(common),
           "spaces": list(vectors), "pairs": {}}
    for a_key, XA in mats.items():
        say(f"  proches selon « {a_key} »…")
        nn, _ = _knn(XA, k)
        m = min(max_rank, nn.shape[1])                # -k plus petit que --rank
        rows_a = np.repeat(np.arange(len(common)), m)
        rows_b = nn[:, :m].ravel()
        rank = np.tile(np.arange(1, m + 1), len(common))
        ok = rows_b >= 0
        rows_a, rows_b, rank = rows_a[ok], rows_b[ok], rank[ok]
        # une paire n'est comptée qu'une fois (A–B et B–A) : on garde le meilleur rang
        lo, hi = np.minimum(rows_a, rows_b), np.maximum(rows_a, rows_b)
        order = np.lexsort((rank, hi, lo))
        lo, hi, rank = lo[order], hi[order], rank[order]
        ra, rb = rows_a[order], rows_b[order]
        first = np.ones(len(lo), dtype=bool)
        first[1:] = (lo[1:] != lo[:-1]) | (hi[1:] != hi[:-1])
        lo, hi, rank = lo[first], hi[first], rank[first]
        # sens de la paire qui a donné le meilleur rang : ra a rb parmi ses plus proches dans A,
        # et c'est depuis ra qu'on mesure leur proximité dans B (le centile n'est pas symétrique)
        ra, rb = ra[first], rb[first]
        for b_key, XB in mats.items():
            if b_key == a_key:
                continue
            c = centiles(XB, ra, rb, sample_ids)
            sel = np.flatnonzero(c < max_centile)
            sel = sel[np.lexsort((rank[sel], c[sel]))]
            # une œuvre « carrefour » (voisine de beaucoup d'autres) ne doit pas remplir la liste
            seen: dict[int, int] = {}
            kept = []
            for j in sel:
                if seen.get(int(lo[j]), 0) >= max_per_work or seen.get(int(hi[j]), 0) >= max_per_work:
                    continue
                seen[int(lo[j])] = seen.get(int(lo[j]), 0) + 1
                seen[int(hi[j])] = seen.get(int(hi[j]), 0) + 1
                kept.append(j)
                if len(kept) >= keep:
                    break
            sel = np.array(kept, dtype=np.int64)
            out["pairs"][f"{a_key}>{b_key}"] = [
                {"a": int(common[lo[j]]), "b": int(common[hi[j]]), "rank": int(rank[j]),
                 "centile": round(float(c[j]), 4)} for j in sel]
            say(f"    loin selon « {b_key} » : {len(np.flatnonzero(c < max_centile))} paires, {len(sel)} gardées")
    return out


def save(analysis, result: dict) -> Path:
    p = Path(analysis.path) / FILE
    p.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return p


def load(analysis) -> dict | None:
    p = Path(analysis.path) / FILE
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
