"""Étiquettes à vérifier : quand toutes les voisines d'une œuvre disent autre chose.

L'audit à l'aveugle (§ 10 de ARCHITECTURE.md) a montré que certaines « erreurs » du modèle
sont en fait des erreurs du catalogue : un « portrait » qui est une scène de genre, un
« Minimalisme » qui est une abstraction gestuelle. On les repère ainsi : parmi les ``k``
plus proches voisines étiquetées, (presque) aucune ne partage l'étiquette de l'œuvre, et
une large majorité en partage une autre.

Ce n'est **jamais une correction automatique** : c'est une liste de cas à regarder. Une
œuvre réellement exceptionnelle (un paysage chez un portraitiste) sort aussi dans cette
liste, et c'est intéressant en soi.

Espace utilisé par défaut : SigLIP 2 quand il existe (il retrouve mieux les catégories de
l'histoire de l'art que DINOv3 : 73 % contre 66 % pour l'artiste au banc d'essai 81k).
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np

SUSPECTS_FILE = "suspects.json"
MIN_MAJORITY = 0.7   # part des voisines qui partagent une même autre étiquette
MAX_OWN = 0.1        # part maximale des voisines qui partagent l'étiquette de l'œuvre
MIN_LABELED = 6      # voisines étiquetées nécessaires pour juger


def _valid(v: str | None) -> bool:
    return bool(v) and not v.lower().startswith("unknown")


def check(own: str | None, neighbor_values: list[str | None], min_labeled: int = MIN_LABELED) -> dict | None:
    """Verdict pour une œuvre et une étiquette, ou None si rien à signaler."""
    if not _valid(own):
        return None
    vals = [v for v in neighbor_values if _valid(v)]
    if len(vals) < min_labeled:
        return None
    counts = Counter(vals)
    top, c = counts.most_common(1)[0]
    own_share = counts.get(own, 0) / len(vals)
    if top == own or c / len(vals) < MIN_MAJORITY or own_share > MAX_OWN:
        return None
    return {"value": own, "suggested": top, "majority": round(c / len(vals), 2),
            "own_share": round(own_share, 2), "labeled_neighbors": len(vals)}


def _knn(X: np.ndarray, k: int, block: int = 4096) -> np.ndarray:
    import faiss

    index = faiss.IndexFlatIP(X.shape[1])
    index.add(X)
    out = np.empty((len(X), k), dtype=np.int64)
    for s in range(0, len(X), block):
        _, nn = index.search(X[s:s + block], k + 1)
        for j, row in enumerate(nn):
            row = [r for r in row if r != s + j and r >= 0][:k]
            out[s + j, :len(row)] = row
            out[s + j, len(row):] = -1
    return out


def find_suspects(ids: np.ndarray, X: np.ndarray, meta: dict[int, dict], keys: list[str],
                  k: int = 10) -> dict[str, list[dict]]:
    """Pour chaque étiquette, la liste des œuvres à vérifier, les cas les plus nets d'abord."""
    nn = _knn(np.ascontiguousarray(X, dtype=np.float32), k)
    out = {}
    for key in keys:
        labels = [meta.get(int(i), {}).get(key) for i in ids]
        if sum(_valid(v) for v in labels) < 2:
            continue
        found = []
        for r, i in enumerate(ids):
            verdict = check(labels[r], [labels[j] for j in nn[r] if j >= 0], min(MIN_LABELED, k))
            if verdict:
                found.append({"id": int(i), **verdict, "neighbors": [int(ids[j]) for j in nn[r][:6] if j >= 0]})
        found.sort(key=lambda d: (-d["majority"], d["own_share"]))
        out[key] = found
    return out


def write_suspects(analysis, settings, keys: list[str], space: str | None = None, k: int = 10) -> Path:
    from ..api.spaces import describe_encoder
    from ..catalog import db
    from ..catalog.metadata import get_metadata
    from ..features.extract import OK
    from ..features.store import FeatureStore
    from ..runs import Run, list_runs

    runs = {describe_encoder(r.manifest["params"].get("encoder", ""))[0]: r
            for r in list_runs("features", runs_dir=settings.runs_dir)
            if r.manifest.get("status") == "complete" and not r.manifest["params"].get("limit")}
    space = space or ("sujet" if "sujet" in runs else None)
    run = runs[space] if space else Run.load(settings.runs_dir / analysis.manifest["parent"])
    space = space or describe_encoder(run.manifest["params"].get("encoder", ""))[0]

    wanted = set(np.load(Path(analysis.path) / "ids.npy").tolist())
    store = FeatureStore.open(run)
    rows = [r for r, i in enumerate(store.ids) if store.status[r] == OK and int(i) in wanted]
    ids = store.ids[rows]
    X = np.asarray(store.global_vectors[rows], dtype=np.float32)
    X /= np.maximum(np.linalg.norm(X, axis=1, keepdims=True), 1e-12)
    conn = db.connect(settings.catalog_path)
    meta = get_metadata(conn, ids.tolist())
    conn.close()

    result = find_suspects(ids, X, meta, keys, k=k)
    path = Path(analysis.path) / SUSPECTS_FILE
    path.write_text(json.dumps({
        "space": space, "features": run.id, "k": k,
        "rule": f"≥ {MIN_MAJORITY:.0%} des voisines étiquetées partagent une autre valeur, "
                f"≤ {MAX_OWN:.0%} partagent celle de l'œuvre",
        "counts": {key: len(v) for key, v in result.items()},
        "suspects": result,
    }, ensure_ascii=False), encoding="utf-8")
    return path


def load_suspects(analysis) -> dict | None:
    path = Path(analysis.path) / SUSPECTS_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
