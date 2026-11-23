"""Les formats de fichiers décrits dans docs/FORMATS.fr.md et docs/FORMATS.md sont bien ceux que le
code écrit. Si ce test échoue, il faut soit corriger le code, soit mettre la doc à jour (et le
noter dans le CHANGELOG : un format qui change n'est plus stable)."""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import numpy as np

from pixplot.analysis import pairbench
from pixplot.catalog.ingest import THUMB_FORMAT, THUMB_SIZES, thumb_path
from pixplot.notebook import KINDS, Notebook
from pixplot.runs import latest_run

DOCS = Path(__file__).resolve().parents[1] / "docs"
DOC_FR = (DOCS / "FORMATS.fr.md").read_text(encoding="utf-8")
DOC_EN = (DOCS / "FORMATS.md").read_text(encoding="utf-8")
MANIFEST_FIELDS = {"stage", "name", "status", "created", "params", "parent", "env"}


def _columns(db: Path, table: str) -> list[str]:
    with sqlite3.connect(db) as c:
        return [r[1] for r in c.execute(f"PRAGMA table_info({table})")]


def test_catalogue_conforme(atlas_env):
    from pixplot.catalog import places

    s, _ = atlas_env
    with sqlite3.connect(s.catalog_path) as c:  # la table des lieux naît au premier import de lieux
        places.ensure(c)
    for table in ("artworks", "metadata", "places"):
        cols = _columns(s.catalog_path, table)
        assert cols, table
        for col in cols:  # chaque colonne réelle est décrite, dans les deux langues
            assert f"`{col}`" in DOC_FR and f"`{col}`" in DOC_EN, (table, col)


def test_vignettes_conformes():
    p = thumb_path(Path("thumbs"), 41274, 256)
    assert p.as_posix() == "thumbs/256/0041/41274.webp" and "thumbs/256/0041/41274.webp" in DOC_FR
    assert THUMB_FORMAT == "webp" and tuple(THUMB_SIZES) == (64, 256, 1024)


def test_runs_conformes(atlas_env):
    s, n = atlas_env
    feats = latest_run("features", runs_dir=s.runs_dir)
    ana = latest_run("analysis", runs_dir=s.runs_dir)
    for run in (feats, ana):
        m = json.loads((Path(run.path) / "manifest.json").read_text(encoding="utf-8"))
        assert MANIFEST_FIELDS <= set(m) and m["status"] == "complete"
        assert re.fullmatch(r".+_\d{8}-\d{6}", Path(run.path).name)
    fp = Path(feats.path)
    assert np.load(fp / "ids.npy").dtype == np.int64
    g = np.load(fp / "global.npy")
    assert g.dtype == np.float16 and g.shape[0] == n
    assert np.load(fp / "status.npy").dtype == np.int8
    ap = Path(ana.path)
    expected = {"ids.npy": np.int64, "coords.npy": np.float32, "clusters.npy": np.int32,
                "neighbors.npy": np.int64, "neighbor_scores.npy": np.float32, "atypicality.npy": np.float32}
    for name, dtype in expected.items():
        arr = np.load(ap / name)
        assert arr.dtype == dtype and arr.shape[0] == n, name
        assert f"`{name}`" in DOC_FR and f"`{name}`" in DOC_EN
    # les voisines sont des identifiants d'œuvres (ou -1), pas des numéros de ligne
    ids = set(np.load(ap / "ids.npy").tolist()) | {-1}
    assert set(np.load(ap / "neighbors.npy").ravel().tolist()) <= ids


def test_paires_conformes():
    assert pairbench.FIELDS == ["a", "b", "type", "origin", "status", "source", "note"]
    assert "`a,b,type,origin,status,source,note`" in DOC_FR and "`a,b,type,origin,status,source,note`" in DOC_EN
    for t in pairbench.TYPES:
        assert f"`{t}`" in DOC_FR and f"`{t}`" in DOC_EN, t
    for st in pairbench.STATUSES:
        assert f"`{st}`" in DOC_FR and f"`{st}`" in DOC_EN, st
    versioned = Path(__file__).resolve().parents[1] / "bench" / "wikiart81k_pairs.csv"
    header = versioned.read_text(encoding="utf-8").splitlines()[0]
    assert f"`{header}`" in DOC_FR and f"`{header}`" in DOC_EN


def test_carnet_conforme(tmp_path):
    db = tmp_path / "notebook.sqlite"
    Notebook(db)
    for col in _columns(db, "entries"):
        assert f"`{col}`" in DOC_FR and f"`{col}`" in DOC_EN, col
    for k in KINDS:
        assert f"`{k}`" in DOC_FR and f"`{k}`" in DOC_EN, k
