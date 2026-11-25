"""Tests du banc d'essai « influence entre artistes » (Wikidata CC0) sur le petit corpus."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest

from pixplot.analysis import influence as I
from pixplot.analysis.pairbench import load_space_matrix
from pixplot.api.data import AtlasData


def test_match_artists_p6002_nom_dates_ambigu_absent():
    cat = {
        "claude-monet": I.CatalogArtist("claude-monet", 10, "Impressionism", 1880, 1870, 1900),
        "pierre-dupont": I.CatalogArtist("pierre-dupont", 8, "Realism", 1860, 1850, 1870),
        "jean-martin": I.CatalogArtist("jean-martin", 6, "Baroque", 1650, 1640, 1660),
        "inconnu-total": I.CatalogArtist("inconnu-total", 5, "Cubism", 1920, 1915, 1925),
    }
    p6002 = [
        {"qid": "Q296", "label": "Claude Monet", "slug": "claude-monet", "birth_year": 1840, "death_year": 1926},
    ]
    names = {
        "pierre dupont": [
            {"qid": "Q101", "label": "Pierre Dupont", "matched_label": "Pierre Dupont", "birth_year": 1825, "death_year": 1885},
            {"qid": "Q102", "label": "Pierre Dupont", "matched_label": "Pierre Dupont", "birth_year": 1950, "death_year": 2010},
        ],
        "jean martin": [
            {"qid": "Q201", "label": "Jean Martin", "matched_label": "Jean Martin", "birth_year": 1615, "death_year": 1675},
            {"qid": "Q202", "label": "Jean Martin", "matched_label": "Jean Martin", "birth_year": 1620, "death_year": 1680},
        ],
    }
    res = I.match_artists(cat, p6002, names)
    assert res["counts"]["p6002"] == 1
    assert res["counts"]["nom_dates"] == 1
    assert res["counts"]["ambigu"] == 1
    assert res["counts"]["absent"] == 1
    assert res["counts"]["surs"] == 2
    assert res["artists"]["claude-monet"]["qid"] == "Q296"
    assert res["artists"]["pierre-dupont"]["qid"] == "Q101"
    assert res["artists"]["jean-martin"]["qid"] is None
    assert res["artists"]["inconnu-total"]["match_status"] == "absent"


def test_controls_and_chronology():
    artists_data = {
        "artists": {
            "a1": {"qid": "Q1", "n_artworks": 10, "birth_year": 1840, "death_year": 1900, "dominant_style": "Impressionism"},
            "a2": {"qid": "Q2", "n_artworks": 10, "birth_year": 1850, "death_year": 1910, "dominant_style": "Impressionism"},
            "a3": {"qid": "Q3", "n_artworks": 10, "birth_year": 1845, "death_year": 1905, "dominant_style": "Realism"},
            "a4": {"qid": "Q4", "n_artworks": 10, "birth_year": 1600, "death_year": 1660, "dominant_style": "Baroque"},
            "a5": {"qid": "Q5", "n_artworks": 3, "birth_year": 1848, "death_year": 1900, "dominant_style": "Impressionism"},
        }
    }
    links = [{"source": "a1", "target": "a2", "property": "P737", "chronology": "possible"}]
    ctrls = I.build_controls(artists_data, links, min_works=5, max_per_tier=50, seed=0)
    # a1 <-> a2 connu : jamais dans les témoins ; a5 a < 5 œuvres : exclu
    for tier, ps in ctrls.items():
        for p in ps:
            assert frozenset((p["source"], p["target"])) != frozenset(("a1", "a2"))
            assert "a5" not in (p["source"], p["target"])
    # a1 -> a3 même époque, style différent -> moyens
    assert any(p["source"] == "a1" and p["target"] == "a3" for p in ctrls["moyens"])
    # a4 -> a2 époque différente (1600 vs 1850), style différent -> faciles
    assert any(p["source"] == "a4" and p["target"] == "a2" for p in ctrls["faciles"])
    # a1 -> a4 (1840 né après mort de a4 en 1660) -> impossibles
    assert any(p["source"] == "a1" and p["target"] == "a4" for p in ctrls["impossibles"])


def test_auc_and_paired_bootstrap():
    pos = np.array([0.9, 0.85, 0.8, 0.75, 0.7, 0.95, 0.88, 0.82])
    neg = np.array([0.4, 0.35, 0.3, 0.45, 0.5, 0.25, 0.38, 0.42])
    assert I.roc_auc(pos, neg) == pytest.approx(1.0)
    assert I.roc_auc(neg, pos) == pytest.approx(0.0)
    b = I.bootstrap_auc(pos, neg, n_boot=200, seed=0)
    assert b["auc"] == pytest.approx(1.0)
    assert b["ci"][0] == pytest.approx(1.0)

    # Regard A parfait vs regard B aléatoire -> écart sûr
    rng = np.random.default_rng(1)
    pos_b = rng.uniform(0.3, 0.6, size=len(pos))
    neg_b = rng.uniform(0.3, 0.6, size=len(neg))
    paired = I.paired_bootstrap_auc(pos, pos_b, neg, neg_b, n_boot=300, seed=0)
    assert paired["diff_auc"] > 0.2
    assert paired["significant"] is True


def test_score_pairs_and_review_csv_on_atlas_env(atlas_env, tmp_path):
    s, _ = atlas_env
    cat_artists, artist_works = I.load_catalog_artists(s.catalog_path)
    assert set(cat_artists) == {"Rouge", "Bleu", "Vert"}
    assert all(a.n_artworks == 6 for a in cat_artists.values())

    data = AtlasData.load(s)
    ids = [int(i) for i in data.ids]
    sp_key = next(iter(data.spaces.runs))
    X, row = load_space_matrix(data.spaces, sp_key, ids)

    # Doublon simulé entre la 1re œuvre de Rouge et la 1re de Bleu
    excl = {artist_works["Rouge"][0]: {artist_works["Bleu"][0]},
            artist_works["Bleu"][0]: {artist_works["Rouge"][0]}}
    pairs = [("Rouge", "Bleu"), ("Vert", "Bleu")]
    sc = I.score_pairs_matrix(pairs, artist_works, X, row, exclude=excl, min_works=5)
    assert set(sc) == {("Rouge", "Bleu"), ("Vert", "Bleu")}
    for v in sc.values():
        assert 0.0 <= v["centile"] <= 1.0
        assert v["median_rank"] >= 1.0
        assert "top_work_pair" in v

    # Export de relecture : rien n'est marqué validé
    artists_data = {
        "artists": {
            slug: {"birth_year": 1800, "death_year": 1870, "dominant_style": f"Style {slug}"}
            for slug in cat_artists
        }
    }
    links = [{
        "source": "Rouge", "target": "Bleu", "source_qid": "Q1", "target_qid": "Q2",
        "property": "P737", "chronology": "possible",
        "references": [{"prop": "P854", "value": "https://example.org/ref", "label": "https://example.org/ref"}],
    }]
    out_csv = tmp_path / "relecture.csv"
    rows = I.export_review_sample(links, artists_data, out_csv, n=30, seed=0)
    assert len(rows) == 1
    with open(out_csv, encoding="utf-8", newline="") as f:
        loaded = list(csv.DictReader(f))
    assert list(loaded[0].keys()) == I.REVIEW_FIELDS
    assert loaded[0]["verdict"] == ""
    assert "example.org" in loaded[0]["references"]


def test_cli_influence_offline_on_atlas_env(atlas_env):
    from pixplot.cli import main

    s, _ = atlas_env
    out_dir = I.influence_dir(s)
    artists_data = {
        "counts": {"p6002": 3, "nom_dates": 0, "ambigu": 0, "absent": 0, "surs": 3, "total": 3},
        "artists": {
            "Rouge": {"slug": "Rouge", "n_artworks": 6, "dominant_style": "Style Rouge",
                      "median_year": 1502, "year_min": 1500, "year_max": 1504,
                      "match_status": "p6002", "qid": "Q1", "label": "Rouge", "birth_year": 1480, "death_year": 1540},
            "Bleu": {"slug": "Bleu", "n_artworks": 6, "dominant_style": "Style Bleu",
                     "median_year": 1602, "year_min": 1600, "year_max": 1604,
                     "match_status": "p6002", "qid": "Q2", "label": "Bleu", "birth_year": 1580, "death_year": 1640},
            "Vert": {"slug": "Vert", "n_artworks": 6, "dominant_style": "Style Vert",
                     "median_year": 1702, "year_min": 1700, "year_max": 1704,
                     "match_status": "p6002", "qid": "Q3", "label": "Vert", "birth_year": 1680, "death_year": 1740},
        },
    }
    links_payload = {
        "counts": {"P737_possible": 1, "P737_impossible": 0, "P1066_possible": 0, "P1066_impossible": 0, "with_references": 0},
        "links": [
            {"source": "Rouge", "target": "Bleu", "source_qid": "Q1", "target_qid": "Q2",
             "property": "P737", "chronology": "possible", "references": []},
        ],
    }
    (out_dir / "artists.json").write_text(json.dumps(artists_data), encoding="utf-8")
    (out_dir / "links.json").write_text(json.dumps(links_payload), encoding="utf-8")
    rc = main(["--data", str(s.data_dir), "influence", "--spaces", "couleur", "--boot", "50"])
    assert rc == 0
    reports = list(out_dir.glob("report_*.json"))
    assert len(reports) == 1
    rep = json.loads(reports[0].read_text(encoding="utf-8"))
    assert "evaluation_median" in rep and "couleur" in rep["scores"]
