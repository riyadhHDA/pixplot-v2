"""Cohérence des notions apprises (ARCHITECTURE § 49) : nette, cohérente dans un seul regard, floue."""

from __future__ import annotations

import numpy as np

from pixplot.analysis import sae


def _unit(X: np.ndarray) -> np.ndarray:
    return (X / np.linalg.norm(X, axis=1, keepdims=True)).astype(np.float32)


def _index(groups: dict[int, np.ndarray], n_features: int) -> dict:
    """Index inversé minimal : pour chaque notion, ses œuvres (rangs = identifiants) par activation décroissante."""
    offsets = np.zeros(n_features + 1, dtype=np.int64)
    ids, scores = [], []
    for f in range(n_features):
        rows = groups.get(f, np.empty(0, dtype=np.int64))
        ids.extend(int(r) for r in rows)
        scores.extend(np.linspace(1.0, 0.5, len(rows)).tolist())
        offsets[f + 1] = offsets[f] + len(rows)
    return {"n_features": n_features, "n_artworks": 0, "offsets": offsets,
            "ids": np.array(ids, dtype=np.int64), "scores": np.array(scores, dtype=np.float32)}


def test_trois_classes():
    rng = np.random.default_rng(1)
    n, d = 2000, 32
    own = rng.normal(size=(n, d))
    other = rng.normal(size=(n, d))
    tight_own = np.arange(0, 50)           # n° 0 : groupée dans les deux regards
    own[tight_own] = rng.normal(size=d) * 4 + rng.normal(size=(50, d)) * 0.5
    other[tight_own] = rng.normal(size=d) * 4 + rng.normal(size=(50, d)) * 0.5
    only_own = np.arange(50, 100)          # n° 1 : groupée dans son regard seulement
    own[only_own] = rng.normal(size=d) * 4 + rng.normal(size=(50, d)) * 0.5
    loose = rng.choice(np.arange(100, n), 50, replace=False)   # n° 2 : au hasard
    small = np.arange(100, 105)            # n° 3 : trop peu d'œuvres, non notée
    ids = np.arange(n, dtype=np.int64)
    index = _index({0: tight_own, 1: only_own, 2: loose, 3: small}, 4)
    res = sae.coherence(index, ids, {"sujet": _unit(own), "forme": _unit(other)}, own="sujet", trials=100)
    f = res["features"]
    assert f["0"]["class"] == "nette"
    assert f["1"]["class"] == "un_regard" and f["1"]["z"]["sujet"] > 3 >= f["1"]["z"]["forme"]
    assert f["2"]["class"] == "floue"
    assert "3" not in f
    assert res["own"] == "sujet" and set(res["baseline"]) == {"sujet", "forme"}


def test_un_seul_regard_disponible():
    """Sans l'autre regard, une notion cohérente est « nette » (pas de « un_regard »)."""
    rng = np.random.default_rng(2)
    X = rng.normal(size=(500, 16))
    X[:40] = rng.normal(size=16) * 4 + rng.normal(size=(40, 16)) * 0.5
    index = _index({0: np.arange(40)}, 1)
    res = sae.coherence(index, np.arange(500, dtype=np.int64), {"forme": _unit(X)}, own="forme", trials=50)
    assert res["features"]["0"]["class"] == "nette"
