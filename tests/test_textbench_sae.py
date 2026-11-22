"""Banc d'essai texte (rangs) et auto-encodeur parcimonieux, sur données synthétiques."""
import numpy as np


def test_ranks_and_summary():
    from pixplot.analysis.textbench import ranks, summary

    rng = np.random.default_rng(0)
    img = rng.normal(size=(50, 8)).astype(np.float32)
    img /= np.linalg.norm(img, axis=1, keepdims=True)
    ids = np.arange(100, 150)
    txt = img[[3, 7, 9]] + 0.01                      # la requête i « décrit » l'œuvre attendue
    txt[2] = -img[9]                                 # une requête ratée : l'œuvre attendue en dernier
    r = ranks(img, ids, txt, [103, 107, 109])
    assert list(r[:2]) == [1, 1] and r[2] == 50
    s = summary(r)
    assert s["R@1"] == round(2 / 3, 4) and s["median"] == 1


def test_sae_learns_planted_notions():
    import pytest
    pytest.importorskip("torch")
    from pixplot.analysis.sae import describe, train

    rng = np.random.default_rng(0)
    atoms = rng.normal(size=(6, 16)).astype(np.float32)
    codes = (rng.random((600, 6)) < 0.25) * rng.random((600, 6))
    X = codes @ atoms + 0.01 * rng.normal(size=(600, 16))
    X = (X / np.linalg.norm(X, axis=1, keepdims=True)).astype(np.float32)
    model = train(X, n_features=32, k=4, epochs=40, batch=64, lr=3e-3, prefixes=(8,), say=lambda m: None)
    assert model["explained_variance"][32] > 0.5          # la reconstruction tient
    assert model["acts"].shape == (600, 32) and ((model["acts"] > 0).sum(axis=1) <= 4).all()
    ids = np.arange(600)
    meta = {i: {"style": "A" if codes[i, 0] > 0.5 else "B"} for i in range(600)}
    feats, baseline = describe(model, ids, X, meta, top=20)
    assert feats and {"feature", "frequency", "top", "labels"} <= set(feats[0])
    assert 0 < baseline["style"] <= 1


def test_meta_label_prend_l_etiquette_dominante():
    from pixplot.analysis import sae

    feat = {"labels": {"style": {"value": "Impressionism", "share": 0.7},
                       "genre": {"value": "landscape", "share": 0.9},
                       "artist": {"value": "claude-monet", "share": 0.3}}}
    assert sae.meta_label(feat) == {"key": "genre", "value": "landscape", "share": 0.9}
    assert sae.meta_label({"labels": {"style": {"value": "Baroque", "share": 0.4}}}) is None
