"""Routes API et découverte des notions apprises (ARCHITECTURE § 37) et de la notion n° 88."""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("faiss")
pytest.importorskip("umap")

from fastapi.testclient import TestClient  # noqa: E402

from pixplot.analysis import sae  # noqa: E402
from pixplot.analysis.layout import load_valid  # noqa: E402
from pixplot.api.app import create_app  # noqa: E402
from pixplot.api.data import AtlasData  # noqa: E402
from pixplot.runs import create_run, latest_run  # noqa: E402


@pytest.fixture
def notions_client(atlas_env, monkeypatch):
    s, n = atlas_env
    # Sans run de notions : /api/notions renvoie 404 et /api/info["notions"] vaut None.
    base_data = AtlasData.load(s)
    feat_run = base_data.features
    ids, X = load_valid(feat_run)
    d = X.shape[1]
    n_features = 96

    # Dictionnaire synthétique : notion 5 alignée sur la 1re œuvre (z >= 5), notion 88 sur la 2e (z < 5).
    W_enc = np.zeros((d, n_features), dtype=np.float32)
    W_enc[:, 5] = X[0]
    W_enc[:, 88] = X[1]
    b_enc = np.full(n_features, -0.5, dtype=np.float32)
    b_enc[5] = 0.2
    b_enc[88] = 0.2
    model = {
        "W_enc": W_enc,
        "b_enc": b_enc,
        "W_dec": W_enc.T.copy(),
        "b_dec": np.zeros(d, dtype=np.float32),
        "mean": np.zeros(d, dtype=np.float32),
        "scale": 1.0,
        "k": 2,
    }
    feats = [
        {
            "feature": 5,
            "frequency": round(6 / len(ids), 5),
            "top": [int(ids[0]), int(ids[1])],
            "labels": {"artist": {"value": "Rouge", "share": 0.9}},
            "iconclass": {"notation": "26B2", "fr": "arc-en-ciel", "z": 7.4},
        },
        {
            "feature": 88,
            "frequency": round(4 / len(ids), 5),
            "top": [int(ids[1]), int(ids[2])],
            "labels": {"style": {"value": "Style Rouge", "share": 0.5}},
            "iconclass": {"notation": "48A5", "fr": "préservation d'une oeuvre d'art", "z": 4.1},
        },
    ]
    run = create_run("analysis", "notions_sujet", {"features": n_features, "k": 2}, parent=feat_run, runs_dir=s.runs_dir)
    try:
        sae.save(run.path, model, feats, {"artist": 0.33}, {"space": "sujet", "explained_variance": {96: 0.7}, "dead": 94})
        run.complete(notions=len(feats), dead=94)
        # le n° 88 n'est « cadre » que pour le calcul relu à l'œil : on désigne celui du test
        monkeypatch.setattr(sae, "FRAMED_RUN", Path(run.path).name)
        # Un run notions_* ne doit jamais masquer la vraie analyse de carte/groupes.
        assert latest_run("analysis", runs_dir=s.runs_dir).id == base_data.analysis.id
        assert sae.latest_notions_run(s.runs_dir).id == run.id
        client = TestClient(create_app(AtlasData.load(s)))
        yield client, ids, n
    finally:
        shutil.rmtree(run.path, ignore_errors=True)


def test_notions_absent_returns_404(atlas_env):
    s, _ = atlas_env
    c = TestClient(create_app(AtlasData.load(s)))
    assert c.get("/api/info").json()["notions"] is None
    assert c.get("/api/notions").status_code == 404
    assert c.get("/api/notions/88").status_code == 404


def test_notions_routes_and_framed_tab(notions_client):
    c, ids, _ = notions_client

    info = c.get("/api/info").json()["notions"]
    assert info is not None
    assert info["space"] == "sujet" and info["count"] == 2 and info["named"] == 1 and info["z_min"] == 5.0
    assert info["framed"]["feature"] == 88 and info["framed"]["count"] >= 1

    lst = c.get("/api/notions").json()
    assert lst["total"] == 2 and lst["named"] == 1
    by_f = {it["feature"]: it for it in lst["items"]}
    # z >= 5 → étiquette Iconclass + lien ; z < 5 → « sans nom »
    assert by_f[5]["named"] is True and by_f[5]["label"] == "arc-en-ciel"
    assert by_f[5]["iconclass"]["url"].startswith("https://iconclass.org/")
    assert by_f[88]["named"] is False and by_f[88]["label"] == "sans nom" and by_f[88]["iconclass"] is None

    # Activations exactes recalculées depuis sae.npz (triées par score décroissant)
    d5 = c.get("/api/notions/5", params={"limit": 10, "highlight_limit": 20}).json()
    assert d5["exact"] is True and d5["total"] >= 1
    assert d5["items"][0]["id"] == int(ids[0])
    assert d5["highlight_ids"][0] == int(ids[0])
    scores = [x["score"] for x in d5["items"]]
    assert scores == sorted(scores, reverse=True)

    # Notion n° 88 (« tableau photographié avec son cadre »)
    d88 = c.get("/api/notions/88", params={"offset": 0, "limit": 2}).json()
    assert d88["exact"] is True and d88["editorial_label"] == "tableau photographié avec son cadre"
    assert d88["label"] == "sans nom" and d88["total"] >= 1
    assert len(d88["items"]) <= 2 and d88["items"][0]["id"] == int(ids[1])

    # Pagination et notion absente
    page2 = c.get("/api/notions/88", params={"offset": 1, "limit": 2}).json()
    assert page2["offset"] == 1 and page2["total"] == d88["total"]
    assert c.get("/api/notions/999").status_code == 404

    # Interface : atlas-notions.js servi et chargé avant atlas-ui.js
    html = c.get("/").text
    assert "atlas-notions.js" in html
    assert html.index("atlas-notions.js") < html.index("atlas-ui.js")
    js = c.get("/atlas-notions.js")
    assert js.status_code == 200 and "renderNotions" in js.text and "renderFramed" in js.text
