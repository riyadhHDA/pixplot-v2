"""Étape 5 : recherche par détail (index des zones + cadre tracé sur une œuvre)."""

import numpy as np
import pytest
from PIL import Image

pytest.importorskip("faiss")
pytest.importorskip("sklearn")

from pixplot.catalog import db  # noqa: E402
from pixplot.catalog.ingest import ingest  # noqa: E402
from pixplot.config import get_settings  # noqa: E402
from pixplot.encoders.colorhist import ColorHistEncoder  # noqa: E402
from pixplot.features.extract import extract  # noqa: E402
from pixplot.index.regions import (RegionIndex, build_region_index, cell_boxes, choose_size,  # noqa: E402
                                   encode_box, find_region_index, square_to_image)


def test_geometry():
    cells = cell_boxes((1, 2, 4))
    assert len(cells) == 21 and cells[0] == (1, (0, 0, 1, 1)) and cells[1] == (2, (0, 0, 0.5, 0.5))
    # œuvre deux fois plus large que haute : bandes en haut et en bas du carré
    assert square_to_image((0, 0, 1, 1), 200, 100) == [0, 0, 1, 1]
    assert square_to_image((0, 0, 0.5, 0.5), 200, 100) == [0, 0, 0.5, 0.5]
    assert square_to_image((0, 0, 1, 0.25), 200, 100) is None  # zone entièrement dans la bande
    assert choose_size(150, 448, 16) == 112 and choose_size(300, 448, 16) == 336
    assert choose_size(500, 224, 16) == 224


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    """12 images de bruit gris ; 5 portent un carré magenta dans leur quart haut-gauche."""
    root = tmp_path_factory.mktemp("regions")
    images = root / "images"
    images.mkdir()
    rng = np.random.default_rng(7)
    marked = []
    for k in range(12):
        arr = rng.integers(60, 190, (200, 200, 3), dtype=np.uint8)
        if k < 5:
            arr[:100, :100] = (230, 20, 220)
            marked.append(f"img_{k:02d}.png")
        Image.fromarray(arr).save(images / f"img_{k:02d}.png")
    s = get_settings(root / "data")
    ingest([images], s.catalog_path, s.thumbs_dir, workers=1)
    feats = extract(ColorHistEncoder(), s.catalog_path, s.runs_dir, batch_size=4, workers=1)
    run = build_region_index(feats, runs_dir=s.runs_dir)
    conn = db.connect(s.catalog_path)
    ids = {r["path"].rsplit("/", 1)[-1]: r["id"] for r in conn.execute("SELECT id, path FROM artworks")}
    return s, feats, run, ids, marked


def test_region_index(corpus):
    s, feats, run, ids, _ = corpus
    assert find_region_index(feats, runs_dir=s.runs_dir).path == run.path
    out = run.manifest["outputs"]
    assert out["artworks"] == 12 and out["count"] == 12 * 20  # grilles 2×2 + 4×4, images carrées


def test_detail_found_in_other_artworks(corpus):
    s, feats, run, ids, marked = corpus
    index = RegionIndex.open(run)
    query = ids[marked[0]]
    path = db.connect(s.catalog_path).execute("SELECT path FROM artworks WHERE id=?", (query,)).fetchone()[0]
    vec = encode_box(ColorHistEncoder(), path, (0.0, 0.0, 0.5, 0.5))
    hits = index.search(vec, k=4, exclude=query)
    found = {h["id"] for h in hits}
    assert found == {ids[m] for m in marked[1:]}          # les 4 autres œuvres marquées
    assert all(h["square_box"][0] < 0.5 and h["square_box"][1] < 0.5 for h in hits)  # au bon endroit


def test_api_region_and_text_status(corpus):
    pytest.importorskip("fastapi")
    pytest.importorskip("umap")
    from fastapi.testclient import TestClient

    from pixplot.analysis.layout import analyze
    from pixplot.api.app import create_app
    from pixplot.api.data import AtlasData

    s, feats, run, ids, marked = corpus
    analyze(feats, runs_dir=s.runs_dir, n_clusters=2, n_neighbors=3)
    c = TestClient(create_app(AtlasData.load(s)))
    st = c.get("/api/search/status").json()
    assert st["region"] is True and st["text"] is False
    r = c.post("/api/search/region", json={"id": ids[marked[0]], "box": [0, 0, 0.5, 0.5], "k": 4}).json()
    assert {x["id"] for x in r["results"]} == {ids[m] for m in marked[1:]}
    assert all(x["box"] == [0.0, 0.0, 0.5, 0.5] or x["box"][2] <= 0.5 for x in r["results"])
    assert c.post("/api/search/region", json={"id": ids[marked[0]], "box": [0, 0, 0.01, 0.01]}).status_code == 400
    assert c.get("/api/search/text", params={"q": "un chat"}).status_code == 503  # pas de SigLIP ici
