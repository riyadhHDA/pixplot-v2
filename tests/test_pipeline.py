"""Pipeline de l'étape 1 de bout en bout, sans GPU (encodeur colorhist)."""

import json

import numpy as np
import pytest
from PIL import Image

from pixplot.catalog import db
from pixplot.catalog.ingest import ingest, thumb_path
from pixplot.encoders.colorhist import ColorHistEncoder
from pixplot.features.extract import FAILED, OK, extract
from pixplot.features.store import FeatureStore
from pixplot.runs import list_runs


def make_corpus(root):
    rng = np.random.default_rng(1)
    (root / "a").mkdir(parents=True)
    (root / "b" / "sub").mkdir(parents=True)
    colors = {"red": (200, 30, 30), "red2": (210, 40, 35), "blue": (30, 40, 200), "green": (30, 180, 40)}
    for name, c in colors.items():
        arr = np.clip(np.array(c) + rng.normal(0, 8, (300, 200, 3)), 0, 255).astype(np.uint8)
        Image.fromarray(arr).save(root / "a" / f"{name}.jpg", quality=92)
    # même nom de fichier dans un autre dossier (collision du v1)
    Image.new("RGB", (120, 400), (240, 240, 40)).save(root / "b" / "red.jpg")
    # copie exacte → doublon
    (root / "b" / "sub" / "copy_of_blue.jpg").write_bytes((root / "a" / "blue.jpg").read_bytes())
    # PNG transparent, TIFF 16 bits, image corrompue
    Image.new("RGBA", (64, 64), (0, 0, 255, 0)).save(root / "b" / "alpha.png")
    Image.fromarray((rng.random((80, 80)) * 65535).astype(np.uint16)).save(root / "b" / "scan16.tif")
    (root / "b" / "broken.jpg").write_bytes(b"pas une image")
    (root / "b" / "notes.txt").write_text("ignoré")


@pytest.fixture
def corpus(tmp_path):
    make_corpus(tmp_path / "images")
    return tmp_path


def test_ingest(corpus):
    cat, thumbs = corpus / "catalog.sqlite", corpus / "thumbs"
    rep = ingest([corpus / "images"], cat, thumbs, workers=1)
    assert rep.discovered == 9 and rep.new == 9
    assert rep.ok == 7 and rep.duplicates == 1 and len(rep.errors) == 1
    assert "broken.jpg" in rep.errors[0][0]

    conn = db.connect(cat)
    rows = {r["path"].split("/images/")[1]: r for r in conn.execute("SELECT * FROM artworks")}
    assert rows["a/red.jpg"]["id"] != rows["b/red.jpg"]["id"]               # pas de collision de nom
    assert rows["b/sub/copy_of_blue.jpg"]["duplicate_of"] == rows["a/blue.jpg"]["id"]
    assert (rows["a/red.jpg"]["width"], rows["a/red.jpg"]["height"]) == (200, 300)
    for size in (64, 256, 1024):
        assert thumb_path(thumbs, rows["a/red.jpg"]["id"], size).exists()

    # Relancer ne retraite rien
    rep2 = ingest([corpus / "images"], cat, thumbs, workers=1)
    assert rep2.new == 0 and rep2.processed == 0


def test_extract_and_similar(corpus):
    cat, runs = corpus / "catalog.sqlite", corpus / "runs"
    ingest([corpus / "images"], cat, corpus / "thumbs", workers=1)
    conn = db.connect(cat)
    ids = {r["path"].split("/images/")[1]: r["id"] for r in conn.execute("SELECT id, path FROM artworks")}

    # Une image disparaît entre l'ingestion et l'extraction → échec isolé, lignes non décalées
    (corpus / "images" / "a" / "green.jpg").unlink()

    run = extract(ColorHistEncoder(), cat, runs, batch_size=3, workers=2)
    out = run.manifest["outputs"]
    assert run.manifest["status"] == "complete"
    assert out["count"] == 7 and out["ok"] == 6 and out["failed"] == 1
    fails = [json.loads(l) for l in (run.path / "failures.jsonl").read_text().splitlines()]
    assert fails[0]["id"] == ids["a/green.jpg"]

    store = FeatureStore.open(run)
    assert store.status[store.ids == ids["a/green.jpg"]][0] == FAILED
    regions = np.load(run.path / "regions.npy")
    assert regions.shape == (7, 21, 64)

    # Le rouge le plus proche du rouge est l'autre rouge
    best_id, score = store.similar(ids["a/red.jpg"], k=3)[0]
    assert best_id == ids["a/red2.jpg"] and score > 0.9
    assert ids["a/green.jpg"] not in [i for i, _ in store.similar(ids["a/blue.jpg"], k=10)]


class Crashing(ColorHistEncoder):
    def __init__(self, crash_after):
        super().__init__()
        self.calls, self.crash_after = 0, crash_after

    def encode(self, batch):
        self.calls += 1
        if self.calls > self.crash_after:
            raise RuntimeError("panne simulée")
        return super().encode(batch)


def test_resume_after_crash(corpus):
    cat, runs = corpus / "catalog.sqlite", corpus / "runs"
    ingest([corpus / "images"], cat, corpus / "thumbs", workers=1)

    with pytest.raises(RuntimeError):
        extract(Crashing(crash_after=1), cat, runs, batch_size=2, workers=1, flush_every=1)
    failed = list_runs("features", status="failed", runs_dir=runs)
    assert len(failed) == 1
    assert (np.load(failed[0].path / "status.npy") == OK).sum() == 2

    enc = Crashing(crash_after=99)
    run = extract(enc, cat, runs, batch_size=2, workers=1)
    assert run.path == failed[0].path                # même run, repris
    assert run.manifest["resumed"] == 1
    assert enc.calls == 3                            # seulement les 5 images restantes
    assert run.manifest["outputs"]["ok"] == 7


def test_import_metadata(corpus):
    from pixplot.catalog.metadata import get_metadata, import_csv

    cat = corpus / "catalog.sqlite"
    ingest([corpus / "images"], cat, corpus / "thumbs", workers=1)
    csv_path = corpus / "images" / "meta.csv"
    csv_path.write_text("path,artist,style\na/red.jpg,Rouge Maître,Fauvisme\nabsent.jpg,X,Y\n", encoding="utf-8")
    rep = import_csv(csv_path, cat)
    assert (rep.rows, rep.matched, rep.unmatched, rep.values) == (2, 1, 1, 2)

    conn = db.connect(cat)
    red = db.find_by_path(conn, corpus / "images" / "a" / "red.jpg")["id"]
    assert get_metadata(conn, [red])[red] == {"artist": "Rouge Maître", "style": "Fauvisme"}
