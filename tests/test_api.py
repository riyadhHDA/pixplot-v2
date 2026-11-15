"""Étape 4 : API de l'Atlas, de bout en bout sur un petit corpus synthétique."""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("faiss")
pytest.importorskip("umap")

from fastapi.testclient import TestClient  # noqa: E402

from pixplot.api.app import create_app  # noqa: E402
from pixplot.api.data import AtlasData  # noqa: E402


@pytest.fixture(scope="module")
def client(atlas_env):
    s, n = atlas_env
    return TestClient(create_app(AtlasData.load(s))), n


def test_info_and_map(client):
    c, n = client
    info = c.get("/api/info").json()
    assert info["count"] == n and info["clusters"] == 3 and info["encoder"] == "colorhist"
    assert {"artist", "style"} <= set(info["metadata_keys"])
    m = c.get("/api/map").json()
    assert len(m["ids"]) == len(m["x"]) == len(m["y"]) == len(m["cluster"]) == len(m["aspect"]) == n
    assert max(map(abs, m["x"] + m["y"])) <= 1.0
    assert abs(m["aspect"][0] - 90 / 120) < 0.01
    artist = m["categories"]["artist"]
    assert set(artist["values"]) == {"Bleu", "Rouge", "Vert"} and len(artist["codes"]) == n


def test_clusters_match_colors(client):
    c, n = client
    groups = c.get("/api/clusters").json()
    assert sum(g["size"] for g in groups) == n
    # chaque groupe correspond à une couleur : l'artiste dominant y est à 100 %
    assert all(g["dominant"]["artist"][0]["share"] == 1.0 for g in groups)


def test_artwork_and_neighbors(client):
    c, _ = client
    m = c.get("/api/map").json()
    first = m["ids"][0]
    a = c.get(f"/api/artwork/{first}").json()
    assert a["id"] == first and a["metadata"]["artist"] in {"Bleu", "Rouge", "Vert"}
    assert a["metadata_sources"]["artist"] == "meta.csv"
    assert len(a["neighbors"]) == 5
    # la plus proche voisine est du même artiste
    best = c.get(f"/api/artwork/{a['neighbors'][0]['id']}").json()
    assert best["metadata"]["artist"] == a["metadata"]["artist"]
    assert c.get("/api/artwork/999999").status_code == 404


def test_images_and_search(client):
    c, _ = client
    first = c.get("/api/map").json()["ids"][0]
    r = c.get(f"/api/thumb/256/{first}")
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
    assert c.get(f"/api/thumb/999/{first}").status_code == 400
    assert c.get("/api/thumb/64/999999").status_code == 404
    assert c.get(f"/api/image/{first}").status_code == 200
    res = c.get("/api/search", params={"q": "rouge"}).json()
    assert res["count"] == 6
    assert c.get("/api/search", params={"q": str(first)}).json()["ids"] == [first]


def test_web_interface_served(client):
    c, _ = client
    r = c.get("/")
    assert r.status_code == 200 and "Atlas" in r.text
    assert c.get("/vendor/deck.gl-9.4.1.min.js").status_code == 200
