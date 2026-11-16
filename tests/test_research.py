"""Espaces de ressemblance, comparateur, carnet, étiquettes à vérifier, dates et lieux,
noms de groupes, encodeur couleur, importateur IIIF."""

import json

import numpy as np
import pytest
from PIL import Image

from tests.conftest import MISLABELED, PALETTE, PER_ARTIST


@pytest.fixture(scope="module")
def env(atlas_env):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from pixplot.analysis.suspects import write_suspects
    from pixplot.api.app import create_app
    from pixplot.api.data import AtlasData
    from pixplot.runs import latest_run

    s, n = atlas_env
    analysis = latest_run("analysis", runs_dir=s.runs_dir)
    write_suspects(analysis, s, ["school"], space="couleur", k=5)
    data = AtlasData.load(s)
    return s, data, TestClient(create_app(data))


def test_spaces_and_compare(env):
    s, data, c = env
    sp = c.get("/api/spaces").json()
    keys = [x["key"] for x in sp["spaces"]]
    assert sp["main"] == "couleur_rvb" and "couleur" in keys
    first = int(data.ids[0])
    a = c.get(f"/api/artwork/{first}?space=couleur&k=4").json()
    assert a["space"] == "couleur" and len(a["neighbors"]) == 4
    assert first not in [x["id"] for x in a["neighbors"]]
    assert c.get(f"/api/artwork/{first}?space=inconnu").status_code == 400
    ids = [int(i) for i in data.ids[:3]]
    cmp = c.get(f"/api/compare?ids={','.join(map(str, ids))}").json()
    for key in keys:
        S = np.array(cmp["similarity"][key], dtype=float)
        assert S.shape == (3, 3) and np.allclose(np.diag(S), 1, atol=1e-2) and np.allclose(S, S.T)
    assert c.get(f"/api/compare?ids={ids[0]}").status_code == 400


def test_color_space_is_centered(env):
    s, data, c = env
    from pixplot.runs import latest_run

    run = latest_run("features", name="color_lab", runs_dir=s.runs_dir)
    assert run.manifest["outputs"]["centered"] is True and (run.path / "center.npy").exists()
    # même artiste (même couleur dominante) → plus proches que deux artistes différents
    reds = [i for i, m in data.meta.items() if m.get("artist") == "Rouge"]
    blue = next(i for i, m in data.meta.items() if m.get("artist") == "Bleu")
    S = data.spaces.pairwise([reds[1], reds[2], blue])["couleur"]
    assert S[0][1] > S[0][2]


def test_notebook_api(env):
    s, data, c = env
    first = int(data.ids[0])
    e = c.post("/api/notebook", json={"title": "Gravures", "kind": "selection", "note": "à suivre",
                                      "artwork_ids": [first], "context": {"requête": "test"}}).json()
    assert e["id"] and e["artwork_ids"] == [first]
    assert c.post("/api/notebook", json={"title": "x", "kind": "inconnu"}).status_code == 400
    up = c.patch(f"/api/notebook/{e['id']}", json={"note": "vu de près"}).json()
    assert up["note"] == "vu de près" and up["title"] == "Gravures"
    assert any(x["id"] == e["id"] for x in c.get("/api/notebook?q=Grav").json()["entries"])
    md = c.get("/api/notebook/export.md")
    assert md.status_code == 200 and "## Gravures" in md.text and "vu de près" in md.text
    assert c.delete(f"/api/notebook/{e['id']}").json() == {"deleted": e["id"]}
    assert c.delete(f"/api/notebook/{e['id']}").status_code == 404


def test_suspect_labels(env):
    s, data, c = env
    from pixplot.analysis.suspects import check

    wrong = next(i for i, m in data.meta.items() if m.get("school") == "Bleu" and m.get("artist") == "Rouge")
    res = c.get("/api/suspects?key=school").json()
    assert [d["id"] for d in res["items"]] == [wrong]
    assert res["items"][0]["suggested"] == "Rouge" and res["space"] == "couleur"
    checks = c.get(f"/api/artwork/{wrong}").json()["label_checks"]
    assert checks and checks[0]["key"] == "school"
    assert check("a", ["b"] * 8 + ["a"]) is None or check("a", ["b"] * 8 + ["a"])["majority"] >= 0.7
    assert check("a", ["b"] * 4) is None                 # trop peu de voisines étiquetées
    assert check("a", ["b"] * 5 + ["a"] * 3) is None     # l'œuvre a des alliées
    assert check("Unknown", ["b"] * 9) is None


def test_years_and_places(env):
    s, data, c = env
    from pixplot.api.data import parse_year

    assert parse_year("vers 1650") == 1650 and parse_year("1650-1655") == 1650
    assert parse_year("c. 890") == 890 and parse_year("inconnue") is None and parse_year(None) is None
    m = c.get("/api/map").json()
    years = [y for y in m["year"] if y is not None]
    assert len(years) == len(PALETTE) * (PER_ARTIST - 1) and min(years) == 1500
    assert sorted({round(v, 2) for v in m["lat"]}) == [41.9, 48.85, 52.37]


def test_group_naming():
    from pixplot.analysis.naming import MANNERS, SUBJECTS, metadata_name, name_from_vectors

    rng = np.random.default_rng(0)
    S = rng.normal(size=(len(SUBJECTS), 256)).astype(np.float32)  # quasi orthogonaux
    M = rng.normal(size=(len(MANNERS), 256)).astype(np.float32)
    S /= np.linalg.norm(S, axis=1, keepdims=True)
    M /= np.linalg.norm(M, axis=1, keepdims=True)
    # dix groupes, chacun centré sur un sujet différent ; le premier a aussi une manière nette
    subjects = [3, 7, 12, 0, 5, 9, 14, 18, 21, 25]
    C = np.stack([S[j] for j in subjects])
    C[0] += 0.9 * M[5]
    C /= np.linalg.norm(C, axis=1, keepdims=True)
    names = name_from_vectors(C, S, M)
    assert [n["terms"][0]["term"] for n in names] == [SUBJECTS[j][0] for j in subjects]
    assert names[0]["name"] == f"{SUBJECTS[3][0]} · {MANNERS[5][0]}"
    meta = [{"artist": "camille-corot", "style": "Realism", "genre": "landscape"}] * 6 + [{"artist": "ivan-shishkin"}] * 4
    assert metadata_name(meta) == "Corot, Shishkin · Realism · Landscape"
    assert metadata_name([{"artist": "Henry Fuseli, 1741–1825"}] * 3) == "Fuseli"


def test_iiif_date_from_label():
    from pixplot.importers.iiif import date_from_label

    # forme des libellés du Yale Center for British Art : artiste, dates de vie, titre, date
    assert date_from_label("Joseph Mallord William Turner, 1775–1851, Dort, 1818") == "1818"
    assert date_from_label("Richard Wilson, ca. 1712–1782, Italian Landscape, between 1760 and 1765") == "between 1760 and 1765"
    assert date_from_label("Henry Fuseli, 1741–1825") is None   # dates de vie seulement
    assert date_from_label("Vue de Delft") is None


def test_iiif_import(tmp_path):
    from pixplot.importers.iiif import import_iiif

    base = "https://musee.example/iiif"
    docs = {
        f"{base}/collection": {"@context": "http://iiif.io/api/presentation/3/context.json", "id": f"{base}/collection",
                               "type": "Collection", "items": [{"id": f"{base}/m1", "type": "Manifest"},
                                                               {"id": f"{base}/m2", "type": "Manifest"}]},
        f"{base}/m1": {  # v3, service Image
            "id": f"{base}/m1", "type": "Manifest", "label": {"fr": ["L'Annonciation"]},
            "metadata": [{"label": {"en": ["Artist"]}, "value": {"none": ["<b>Fra Angelico</b>"]}},
                         {"label": {"fr": ["Date"]}, "value": {"none": ["vers 1440"]}}],
            "rights": "http://creativecommons.org/publicdomain/zero/1.0/",
            "items": [{"id": f"{base}/m1/c1", "type": "Canvas", "items": [{"type": "AnnotationPage", "items": [
                {"type": "Annotation", "body": {"id": f"{base}/img1/full/max/0/default.jpg", "type": "Image",
                                                "service": [{"id": f"{base}/img1", "type": "ImageService3"}]}}]}]}]},
        f"{base}/m2": {  # v2, image sans service
            "@id": f"{base}/m2", "@type": "sc:Manifest", "label": "Vue de Delft",
            "metadata": [{"label": "Creator", "value": "Vermeer"}, {"label": "Inventory number", "value": "SK-1"}],
            "sequences": [{"canvases": [{"@id": f"{base}/m2/c1", "images": [
                {"resource": {"@id": f"{base}/img2.jpg", "@type": "dctypes:Image"}}]}]}]},
    }
    fetched = []

    def fake_get(url, dest):
        fetched.append(url)
        Image.new("RGB", (40, 30), (120, 80, 40)).save(dest, "JPEG")

    rep = import_iiif([f"{base}/collection"], tmp_path, max_size=800, delay=0, fetch=docs.__getitem__, get=fake_get)
    assert rep.manifests == 2 and rep.images == 2 and not rep.failed
    assert fetched == [f"{base}/img1/full/!800,800/0/default.jpg", f"{base}/img2.jpg"]
    import csv
    rows = list(csv.DictReader(open(rep.csv_path, encoding="utf-8")))
    assert rows[0]["title"] == "L'Annonciation" and rows[0]["artist"] == "Fra Angelico" and rows[0]["date"] == "vers 1440"
    assert rows[0]["rights"].startswith("http://creativecommons") and rows[1]["identifier"] == "SK-1"
    assert (tmp_path / rows[1]["path"]).exists()
    # reprise : rien n'est retéléchargé
    rep2 = import_iiif([f"{base}/collection"], tmp_path, delay=0, fetch=docs.__getitem__, get=fake_get)
    assert rep2.images == 0 and rep2.skipped == 2 and len(fetched) == 2


def test_space_maps(env):
    s, data, c = env
    from pixplot.analysis.spacemaps import available_maps, compute_space_maps

    done = compute_space_maps(data.analysis, s, say=lambda m: None)
    assert list(done) == ["couleur"]                     # l'espace de l'analyse n'a pas de 2e carte
    assert available_maps(data.analysis) == ["couleur"]
    lay = c.get("/api/layout/couleur").json()
    assert len(lay["x"]) == len(data.ids) and all(-1.01 <= v <= 1.01 for v in lay["x"] if v is not None)
    assert c.get("/api/layout/inconnu").status_code == 404
    assert c.get("/api/info").json()["space_maps"] == ["couleur"]
    # déjà calculée : rien n'est refait sans --force
    assert compute_space_maps(data.analysis, s, say=lambda m: None) == done


def test_world_basemap_is_vendored():
    from pathlib import Path

    topo = json.loads((Path(__file__).parents[1] / "web" / "vendor" / "world-110m.json").read_text(encoding="utf-8"))
    assert topo["type"] == "Topology" and {"land", "countries"} <= set(topo["objects"]) and topo["transform"]


def test_pair_ranks_are_exact():
    from pixplot.analysis.pairbench import Pair, ranks_in_space, score_pairs

    rng = np.random.default_rng(1)
    X = rng.normal(size=(50, 8)).astype(np.float32)
    X /= np.linalg.norm(X, axis=1, keepdims=True)
    S = X @ X.T
    np.fill_diagonal(S, -np.inf)
    a, b = 3, 17
    expected = int((S[a] > S[a, b]).sum()) + 1
    assert ranks_in_space(X, np.array([a]), np.array([b]))[0] == expected
    # une paire identique à elle-même près : rang 1, centile 1
    X[b] = X[a]
    res, detail = score_pairs([Pair(100 + a, 100 + b, "filiation")], {"forme": (X, {100 + i: i for i in range(50)})})
    assert res[0].r10 == 1.0 and res[0].median_rank == 1 and res[0].centile == pytest.approx(1.0)
    assert detail[(100 + a, 100 + b, "filiation")]["forme"] == (1, 1)


def test_pairs_file_and_metadata_pairs(tmp_path):
    from pixplot.analysis.pairbench import Pair, add_pair, load_pairs, metadata_pairs

    path = tmp_path / "pairs.csv"
    add_pair(path, Pair(1, 2, "meme_sujet", source="Honour et Fleming, p. 670"))
    add_pair(path, Pair(2, 1, "meme_sujet", status="proposée"))          # même paire, ordre inversé
    add_pair(path, Pair(1, 2, "meme_palette"))
    pairs = load_pairs(path)
    assert len(pairs) == 2 and {p.status for p in pairs if p.type == "meme_sujet"} == {"proposée"}
    with pytest.raises(ValueError):
        add_pair(path, Pair(1, 2, "inconnu"))
    with pytest.raises(ValueError):
        add_pair(path, Pair(3, 3, "meme_sujet"))

    meta = {}
    for n in range(400):
        meta[n] = {"artist": f"a{n % 20}", "style": ["Pointillism", "Fauvism", "Realism", "Baroque"][n % 4],
                   "genre": ["portrait", "landscape", "still_life"][n % 3]}
    out = metadata_pairs(meta, n=30, seed=0)
    by = lambda t: [p for p in out if p.type == t]
    assert by("meme_sujet") and all(meta[p.a]["genre"] == meta[p.b]["genre"] and meta[p.a]["style"] != meta[p.b]["style"]
                                     and meta[p.a]["artist"] != meta[p.b]["artist"] for p in by("meme_sujet"))
    assert all(meta[p.a]["artist"] == meta[p.b]["artist"] and meta[p.a]["style"] != meta[p.b]["style"]
               for p in by("meme_main"))
    fac = by("meme_facture")
    assert fac and all(meta[p.a]["style"] == meta[p.b]["style"] == p.note and meta[p.a]["genre"] != meta[p.b]["genre"]
                       for p in fac)
    assert {p.note for p in fac} == {"Pointillism", "Fauvism"}
    assert all(p.origin == "métadonnées" for p in out)


def test_pairs_api(env):
    s, data, c = env
    a, b = int(data.ids[0]), int(data.ids[1])
    r = c.get(f"/api/pairs?ids={a},{b}").json()
    assert r["pairs"] == [] and "meme_facture" in [t["key"] for t in r["types"]]
    assert c.post("/api/pairs", json={"a": a, "b": b, "type": "inconnu"}).status_code == 400
    assert c.post("/api/pairs", json={"a": a, "b": 999999, "type": "meme_sujet"}).status_code == 404
    p = c.post("/api/pairs", json={"a": a, "b": b, "type": "meme_palette", "source": "essai"}).json()
    assert p["origin"] == "annotée" and p["status"] == "validée"
    assert [x["type"] for x in c.get(f"/api/pairs?ids={b},{a}").json()["pairs"]] == ["meme_palette"]


def test_version_is_consistent():
    import tomllib
    from pathlib import Path

    import pixplot

    root = Path(__file__).parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["version"] == pixplot.__version__
    assert f"## {pixplot.__version__} " in (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## {pixplot.__version__} " in (root / "CHANGELOG.fr.md").read_text(encoding="utf-8")
