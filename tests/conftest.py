"""Petit corpus synthétique complet (catalogue, métadonnées, vecteurs, analyse), partagé
par les tests de l'API, du Research Pack et du serveur MCP."""

import numpy as np
import pytest
from PIL import Image

PALETTE = {"Rouge": (200, 40, 40), "Bleu": (40, 60, 200), "Vert": (40, 170, 60)}
PER_ARTIST = 6


@pytest.fixture(scope="session")
def atlas_env(tmp_path_factory):
    pytest.importorskip("faiss")
    pytest.importorskip("umap")
    from pixplot.analysis.layout import analyze
    from pixplot.catalog.ingest import ingest
    from pixplot.catalog.metadata import import_csv
    from pixplot.config import get_settings
    from pixplot.encoders.colorhist import ColorHistEncoder
    from pixplot.features.extract import extract

    root = tmp_path_factory.mktemp("atlas")
    images = root / "images"
    images.mkdir()
    rng = np.random.default_rng(3)
    rows = ["path,artist,style"]
    for artist, color in PALETTE.items():
        for k in range(PER_ARTIST):
            arr = np.clip(np.array(color) + rng.normal(0, 12, (120, 90, 3)), 0, 255).astype(np.uint8)
            Image.fromarray(arr).save(images / f"{artist}_{k}.jpg")
            rows.append(f"{artist}_{k}.jpg,{artist},Style {artist}")
    (images / "meta.csv").write_text("\n".join(rows), encoding="utf-8")

    s = get_settings(root / "data")
    ingest([images], s.catalog_path, s.thumbs_dir, workers=1)
    import_csv(images / "meta.csv", s.catalog_path)
    feats = extract(ColorHistEncoder(), s.catalog_path, s.runs_dir, batch_size=8, workers=1)
    analyze(feats, runs_dir=s.runs_dir, n_clusters=3, n_neighbors=5, use_hdbscan=False)
    return s, len(PALETTE) * PER_ARTIST
