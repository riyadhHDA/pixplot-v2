"""Petit corpus synthétique complet (catalogue, métadonnées, vecteurs, analyse), partagé
par les tests de l'API, du Research Pack et du serveur MCP."""

import numpy as np
import pytest
from PIL import Image

PALETTE = {"Rouge": (200, 40, 40), "Bleu": (40, 60, 200), "Vert": (40, 170, 60)}
PER_ARTIST = 6
CITIES = {"Rouge": (48.85, 2.35), "Bleu": (41.9, 12.5), "Vert": (52.37, 4.9)}
MISLABELED = "Rouge_0.jpg"  # « école » volontairement fausse : doit sortir dans les étiquettes à vérifier


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
    rows = ["path,artist,style,date,latitude,longitude,school"]
    for n, (artist, color) in enumerate(PALETTE.items()):
        for k in range(PER_ARTIST):
            arr = np.clip(np.array(color) + rng.normal(0, 12, (120, 90, 3)), 0, 255).astype(np.uint8)
            name = f"{artist}_{k}.jpg"
            Image.fromarray(arr).save(images / name)
            lat, lon = CITIES[artist]
            school = "Bleu" if name == MISLABELED else artist
            date = "" if k == 5 else f"vers {1500 + 100 * n + k}"
            rows.append(f"{name},{artist},Style {artist},{date},{lat},{lon},{school}")
    (images / "meta.csv").write_text("\n".join(rows), encoding="utf-8")

    s = get_settings(root / "data")
    ingest([images], s.catalog_path, s.thumbs_dir, workers=1)
    import_csv(images / "meta.csv", s.catalog_path)
    from pixplot.encoders.colorlab import ColorLabEncoder

    feats = extract(ColorHistEncoder(), s.catalog_path, s.runs_dir, batch_size=8, workers=1)
    extract(ColorLabEncoder(), s.catalog_path, s.runs_dir, batch_size=8, workers=1)  # second espace : « couleur »
    analyze(feats, runs_dir=s.runs_dir, n_clusters=3, n_neighbors=5, use_hdbscan=False)
    return s, len(PALETTE) * PER_ARTIST
