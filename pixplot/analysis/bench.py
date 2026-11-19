"""Banc d'essai : quel modèle / quelle résolution retrouve le mieux ce que l'historien attend ?

Deux mesures, à partir des métadonnées du catalogue :

1. **Étiquettes** (artiste, style, genre...) : pour chaque œuvre étiquetée, part de ses
   voisines qui partagent l'étiquette. P@1 = la plus proche ; P@k = les k plus proches.
   Les valeurs « Unknown ... » sont ignorées. « hasard » = ce qu'on obtiendrait au hasard.

2. **Paires connues** : une œuvre qui porte ``variant_of`` (chemin de l'original) est une
   copie, une reproduction, une gravure inversée... On mesure si l'original est retrouvé
   en 1ʳᵉ position (R@1) ou dans les k premières (R@k), par type de variante
   (``variant_type``).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..catalog.metadata import get_metadata
from ..features.extract import OK
from ..runs import Run


@dataclass
class LabelScore:
    key: str
    p1: float
    pk: float
    chance: float
    n: int


@dataclass
class PairScore:
    variant_type: str
    r1: float
    rk: float
    n: int


def _neighbors(X: np.ndarray, k: int) -> np.ndarray:
    """Indices des k plus proches voisins de chaque ligne (soi-même exclu)."""
    try:
        import faiss
        index = faiss.IndexFlatIP(X.shape[1])
        index.add(X)
        nn = np.concatenate([index.search(X[s:s + 4096], k + 1)[1] for s in range(0, len(X), 4096)])
    except ImportError:  # pragma: no cover
        # sans FAISS : par blocs (X @ X.T en entier ferait 26 Go pour 80 000 œuvres)
        nn = np.concatenate([np.argsort(-(X[s:s + 1024] @ X.T), axis=1)[:, :k + 1]
                             for s in range(0, len(X), 1024)])
    out = np.empty((len(X), k), dtype=np.int64)
    for i, row in enumerate(nn):
        row = [j for j in row if j != i and j >= 0][:k]
        out[i, :len(row)] = row
        out[i, len(row):] = -1
    return out


def load_vectors(run: Run) -> tuple[np.ndarray, np.ndarray]:
    p = Path(run.path)
    keep = np.load(p / "status.npy") == OK
    ids = np.load(p / "ids.npy")[keep]
    X = np.ascontiguousarray(np.load(p / "global.npy")[keep], dtype=np.float32)
    X /= np.maximum(np.linalg.norm(X, axis=1, keepdims=True), 1e-12)   # float16 → norme 1
    return ids, X


def label_scores(ids, nn, meta, keys, exclude: np.ndarray | None = None) -> list[LabelScore]:
    out = []
    for key in keys:
        labels = np.array([meta[int(i)].get(key) or "" for i in ids], dtype=object)
        valid = np.array([bool(l) and not l.lower().startswith("unknown") for l in labels])
        if exclude is not None:
            valid &= ~exclude
        if valid.sum() < 2:
            continue
        p1, pk = [], []
        for q in np.flatnonzero(valid):
            neigh = [j for j in nn[q] if j >= 0 and valid[j]]
            if neigh:
                same = labels[neigh] == labels[q]
                p1.append(float(same[0]))
                pk.append(float(same.mean()))
        n = int(valid.sum())
        chance = sum((c / n) ** 2 for c in Counter(labels[valid]).values())
        out.append(LabelScore(key, float(np.mean(p1)), float(np.mean(pk)), chance, n))
    return out


def pair_scores(ids, nn, meta, path_to_id: dict[str, int], k: int) -> list[PairScore]:
    """Les autres variantes du même original (« sœurs ») sont ignorées : elles se ressemblent
    entre elles par construction et masqueraient l'original. ``nn`` doit donc contenir au
    moins k + (nombre de sœurs) voisins."""
    row_of = {int(i): r for r, i in enumerate(ids)}
    hits: dict[str, list[tuple[bool, bool]]] = defaultdict(list)
    for r, i in enumerate(ids):
        m = meta[int(i)]
        original = m.get("variant_of")
        if not original:
            continue
        target = path_to_id.get(Path(original).resolve().as_posix())
        if target is None or target not in row_of:
            continue
        found = [int(ids[j]) for j in nn[r]
                 if j >= 0 and meta[int(ids[j])].get("variant_of") != original][:k]
        hit = (bool(found) and found[0] == target, target in found)
        hits[m.get("variant_type", "variante")].append(hit)
        hits["(toutes)"].append(hit)
    return [PairScore(t, float(np.mean([h[0] for h in v])), float(np.mean([h[1] for h in v])), len(v))
            for t, v in sorted(hits.items())]


def run_bench(run: Run, conn, keys: list[str], k: int = 10) -> tuple[list[LabelScore], list[PairScore]]:
    ids, X = load_vectors(run)
    meta = get_metadata(conn, ids.tolist())
    originals = Counter(m.get("variant_of") for m in meta.values() if m.get("variant_of"))
    max_siblings = max(originals.values(), default=1) - 1
    nn = _neighbors(X, k + max_siblings)
    # Les variantes ne doivent pas fausser les scores d'étiquettes (elles copient leur original).
    is_variant = np.array([bool(meta[int(i)].get("variant_of")) for i in ids])
    labels = label_scores(ids, nn[:, :k], meta, keys, exclude=is_variant)
    path_to_id = {r["path"]: r["id"] for r in conn.execute("SELECT id, path FROM artworks")}
    pairs = pair_scores(ids, nn, meta, path_to_id, k)
    return labels, pairs
