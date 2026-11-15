"""Étape 3 : groupes e-means, carte UMAP, voisinages, atypicité (sur vecteurs synthétiques)."""

import json

import numpy as np
import pytest

from pixplot.analysis.layout import atypicality, default_cluster_count, normalize_coords
from pixplot.runs import create_run


def fake_features(runs_dir, n_per=30, centers=4, dim=32, seed=0):
    """Un run « features » sans images : 4 nuages de points bien séparés + 2 isolés."""
    rng = np.random.default_rng(seed)
    c = rng.normal(size=(centers, dim))
    X = np.concatenate([c[i] + rng.normal(0, 0.05, (n_per, dim)) for i in range(centers)]
                       + [rng.normal(size=(2, dim)) * 3])
    X /= np.linalg.norm(X, axis=1, keepdims=True)
    run = create_run("features", "fake", {"encoder": "fake"}, runs_dir=runs_dir)
    n = len(X)
    np.save(run.path / "ids.npy", np.arange(100, 100 + n))
    np.save(run.path / "global.npy", X.astype(np.float16))
    status = np.ones(n, dtype=np.int8)
    status[0] = 2  # une image en échec : doit être ignorée
    np.save(run.path / "status.npy", status)
    run.complete(count=n)
    return run, centers, n_per


def test_helpers():
    assert default_cluster_count(100) == 8 and default_cluster_count(10_000) == 50
    assert default_cluster_count(10_000_000) == 200
    c = normalize_coords(np.array([[0, 0], [2, 1], [1, 0.5], [100, 0]], dtype=np.float32), clip_percent=0)
    assert np.abs(c).max() <= 1.0
    scores = np.array([[0.9, 0.9], [0.1, 0.1], [0.5, 0.5]])
    a = atypicality(scores)
    assert a[1] == 1.0 and a[0] == 0.0  # la moins entourée est la plus atypique


def test_analyze_end_to_end(tmp_path):
    pytest.importorskip("faiss")
    pytest.importorskip("umap")
    from pixplot.analysis.layout import analyze

    features, centers, n_per = fake_features(tmp_path)
    run = analyze(features, runs_dir=tmp_path, n_clusters=centers, n_neighbors=5, use_hdbscan=True)
    p = run.path
    ids = np.load(p / "ids.npy")
    assert 100 not in ids and len(ids) == centers * n_per + 2 - 1
    assert np.load(p / "coords.npy").shape == (len(ids), 2)
    assert np.abs(np.load(p / "coords.npy")).max() <= 1.0
    assert np.load(p / "neighbors.npy").shape == (len(ids), 5)

    # Les 4 nuages sont retrouvés : chaque nuage tombe dans un seul groupe e-means.
    labels = np.load(p / "clusters.npy")
    for i in range(centers):
        block = labels[max(0, i * n_per - 1):(i + 1) * n_per - 1]
        assert len(set(block.tolist())) == 1
    summary = json.loads((p / "clusters.json").read_text(encoding="utf-8"))
    assert sum(e["size"] for e in summary) == len(ids)

    # Les deux points isolés sont parmi les plus atypiques.
    a = np.load(p / "atypicality.npy")
    assert set(np.argsort(-a)[:2].tolist()) == {len(ids) - 2, len(ids) - 1}

    # Reproductible : même graine → même carte.
    run2 = analyze(features, runs_dir=tmp_path, n_clusters=centers, n_neighbors=5)
    assert np.allclose(np.load(p / "coords.npy"), np.load(run2.path / "coords.npy"), atol=1e-4)
