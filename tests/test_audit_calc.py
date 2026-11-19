"""Corrections des calculs relevées par l'audit de Gemini 4 Argon (points 4, 7, 12, 13, 14)."""
import numpy as np


def _graph(edges, n):
    import igraph as ig

    G = ig.Graph(n=n, edges=[(a, b) for a, b, _ in edges])
    G.es["weight"] = [w for _, _, w in edges]
    return G


def test_merge_small_keeps_small_community_whole():
    """Point 7 : une petite communauté reliée à deux grandes n'est pas coupée entre elles."""
    from pixplot.analysis.communities import merge_small

    # A = 0..5, B = 6..11 (grandes), petite = 12..14, plus liée à B au total
    edges = [(i, j, 1.0) for i in range(6) for j in range(i + 1, 6)]
    edges += [(i, j, 1.0) for i in range(6, 12) for j in range(i + 1, 12)]
    edges += [(12, 13, 1.0), (13, 14, 1.0), (12, 0, 0.9), (13, 6, 0.6), (14, 7, 0.6)]
    labels = np.array([0] * 6 + [1] * 6 + [2] * 3)
    out = merge_small(_graph(edges, 15), labels, min_size=5)
    assert out.max() + 1 == 2
    assert len(set(out[12:15])) == 1                    # rattachée en bloc…
    assert out[12] == out[6]                            # …à B (1,2 contre 0,9 pour A)


def test_merge_small_isolated_and_chain():
    """Une petite communauté sans lien reste seule ; deux petites voisines se rejoignent."""
    from pixplot.analysis.communities import merge_small

    edges = [(0, 1, 1.0), (1, 2, 1.0), (2, 3, 1.0)]      # 0-1 et 2-3 : deux petites reliées
    labels = np.array([0, 0, 1, 1, 2])                   # 4 : isolée
    out = merge_small(_graph(edges, 5), labels, min_size=3)
    assert out[0] == out[1] == out[2] == out[3]
    assert out[4] != out[0]


def test_cell_boxes_follow_patch_split():
    """Point 12 : 14 patchs en 4 bandes = 4 + 4 + 3 + 3, les cadres suivent."""
    from pixplot.index.regions import cell_boxes, patches_per_side

    assert patches_per_side({"input_size": 224, "patch_size": 16}) == 14
    assert patches_per_side({"input_size": 224, "patch_size": None}) is None
    four = [box for g, box in cell_boxes((4,), 14)]
    assert np.isclose(four[0][2], 4 / 14) and np.isclose(four[2][0], 8 / 14) and four[3][2] == 1.0
    assert cell_boxes((1, 2, 4), 28) == cell_boxes((1, 2, 4))   # 28 patchs : rien ne change


def test_resumable_zone_run_skips_small_complete_trial(tmp_path):
    """Point 4 : un petit essai terminé après un grand run interrompu ne le cache plus."""
    from pixplot.index.textzones import find_resumable_zone_run
    from pixplot.runs import create_run

    params = {"encoder": "e", "weights": "w", "input_size": 384, "grids": [2, 4]}
    ids = np.arange(50)
    big = create_run("features", "zones_e", params, runs_dir=tmp_path)
    np.save(big.path / "ids.npy", ids)
    big.fail("interrompu")
    trial = create_run("features", "zones_e", {**params, "limit": 10}, runs_dir=tmp_path)
    np.save(trial.path / "ids.npy", ids[:10])
    trial.complete()
    found = find_resumable_zone_run(tmp_path, ids, params)
    assert found is not None and found.path == big.path
    assert find_resumable_zone_run(tmp_path, ids, {**params, "input_size": 512}) is None


def test_neighbors_blocks_match_single_search():
    """Point 14 : la recherche par blocs donne les mêmes voisines."""
    from pixplot.analysis.layout import neighbors

    rng = np.random.default_rng(0)
    X = rng.normal(size=(9000, 16)).astype(np.float32)
    X /= np.linalg.norm(X, axis=1, keepdims=True)
    rows, scores = neighbors(X, k=5)
    S = X[:50] @ X.T
    S[np.arange(50), np.arange(50)] = -np.inf
    assert np.array_equal(rows[:50], np.argsort(-S, axis=1)[:, :5])


def test_maps_index_keeps_other_entries(tmp_path):
    """La carte d'essai LocalMAP s'ajoute à maps.json sans effacer les cartes des regards."""
    import json

    from pixplot.analysis.spacemaps import _write_index

    _write_index(tmp_path, {"sujet": {"file": "sujet.npy"}})
    _write_index(tmp_path, {"forme_localmap": {"file": "forme_localmap.npy"}})
    assert set(json.loads((tmp_path / "maps.json").read_text(encoding="utf-8"))) == {"sujet", "forme_localmap"}


def test_localmap_small_corpus():
    """LocalMAP (facultatif) donne une carte normalisée dans [-1, 1]."""
    import pytest

    pacmap = pytest.importorskip("pacmap")
    from pixplot.analysis.layout import normalize_coords

    Z = np.random.default_rng(0).normal(size=(300, 16)).astype(np.float32)
    xy = normalize_coords(pacmap.LocalMAP(n_neighbors=10, random_state=42, apply_pca=False).fit_transform(Z, init="pca"))
    assert xy.shape == (300, 2) and np.abs(xy).max() <= 1.0
