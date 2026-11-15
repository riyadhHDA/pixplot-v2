"""Audit à l'aveugle : les étiquettes ne servent qu'à évaluer, et l'audit repère les échecs."""

import pytest

from pixplot.analysis.audit import audit, write_report
from pixplot.catalog import db
from pixplot.catalog.metadata import import_csv
from pixplot.runs import latest_run


def test_audit_finds_mislabelled_artwork(atlas_env, tmp_path):
    pytest.importorskip("sklearn")
    s, n = atlas_env
    conn = db.connect(s.catalog_path)
    paths = {r["path"].rsplit("/", 1)[-1]: r["path"] for r in conn.execute("SELECT path FROM artworks")}
    # Nouvelle étiquette « couleur_test » : juste partout, sauf une image rouge étiquetée « Bleu ».
    rows = ["path,couleur_test"]
    for name, p in paths.items():
        if not name.endswith(".jpg"):
            continue
        label = name.split("_")[0]
        rows.append(f"{p},{'Bleu' if name == 'Rouge_0.jpg' else label}")
    csv_path = tmp_path / "labels.csv"
    csv_path.write_text("\n".join(rows), encoding="utf-8")
    import_csv(csv_path, s.catalog_path, source="test")

    analysis = latest_run("analysis", runs_dir=s.runs_dir)
    [r] = audit(analysis, conn, ["couleur_test"], k=5, min_count=3)
    assert r.n == n and r.values == 3
    assert r.purity > 0.9 and r.nmi > 0.7               # les groupes suivent les couleurs
    rouge0 = conn.execute("SELECT id FROM artworks WHERE path LIKE '%Rouge_0.jpg'").fetchone()[0]
    assert [f["id"] for f in r.failures] == [rouge0]     # la seule erreur d'étiquette est repérée
    assert r.failures[0]["neighbor_labels"][0][0] == "Rouge"
    bleu = next(d for d in r.per_value if d["value"] == "Bleu")
    assert bleu["top_confusions"][0][0] == "Rouge"

    md, page = write_report([r], analysis, conn, s.thumbs_dir, tmp_path / "audit", k=5)
    assert "couleur_test" in md.read_text(encoding="utf-8") and page.stat().st_size > 1000
