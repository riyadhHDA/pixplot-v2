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
    # le fichier de citation (bouton « Cite this repository », Zenodo) suit la version
    cff = (root / "CITATION.cff").read_text(encoding="utf-8").splitlines()
    assert f"version: {pixplot.__version__}" in cff


def test_leiden_communities_are_nested_and_recover_blobs(tmp_path):
    pytest.importorskip("leidenalg")
    from sklearn.metrics import adjusted_rand_score

    from pixplot.analysis import communities as C

    rng = np.random.default_rng(0)
    # 4 « familles » de 3 « groupes » chacune : centres de groupe proches de leur famille
    fam_c = rng.normal(size=(4, 32))
    centers = np.concatenate([f + 0.3 * rng.normal(size=(3, 32)) for f in fam_c])
    truth = np.repeat(np.arange(12), 40)
    X = (centers[truth] + 0.2 * rng.normal(size=(len(truth), 32))).astype(np.float32)
    X /= np.linalg.norm(X, axis=1, keepdims=True)
    c = C.compute("forme", np.arange(1000, 1000 + len(X)), X, n_groups=12, n_families=4, k=10,
                  say=lambda m: None)
    assert c.groups.max() + 1 == 12 and adjusted_rand_score(truth, c.groups) > 0.9
    assert c.families.shape == (12,) and c.families.max() + 1 == 4
    fam_of_work = c.families[c.groups]                      # emboîtement : chaque groupe a une famille
    assert adjusted_rand_score(truth // 3, fam_of_work) > 0.9
    assert np.bincount(c.groups).min() >= C.MIN_SIZE

    class A:  # run d'analyse minimal
        path = tmp_path
    C.save(A, c)
    back = C.load(A, "forme")
    assert C.available(A) == ["forme"] and back["groups"].tolist() == c.groups.tolist()
    assert back["families"].tolist() == c.families.tolist()
    assert np.array_equal(back["ids"], c.ids)


def test_pair_lift_and_label_agreement():
    from pixplot.analysis.communities import label_agreement, pair_lift
    from pixplot.analysis.pairbench import Pair

    labels = np.array([0, 0, 1, 1, 2, 2])
    row = {10 + i: i for i in range(6)}
    lift = pair_lift(labels, row, [Pair(10, 11, "filiation"), Pair(10, 12, "temoin"), Pair(12, 13, "filiation")])
    assert lift["filiation"] == pytest.approx(3.0) and lift["temoin"] == 0
    assert label_agreement(labels, ["a", "a", "b", "b", "c", "c"]) == pytest.approx(1.0)
    assert label_agreement(labels, ["a", "Unknown", "b", "b", "c", "c"]) == pytest.approx(1.0)


def test_communities_api(env):
    pytest.importorskip("leidenalg")
    s, data, c = env
    from pixplot.analysis import communities as C
    from pixplot.analysis.pairbench import load_space_matrix

    ids = [int(i) for i in data.ids]
    X, row = load_space_matrix(data.spaces, "couleur", ids)
    present = np.array([i for i in ids if i in row])
    C.save(data.analysis, C.compute("couleur", present, X, n_groups=4, n_families=2, k=5, say=lambda m: None))
    assert "couleur" in c.get("/api/info").json()["communities"]
    r = c.get("/api/communities/couleur").json()
    assert len(r["group"]) == len(ids) and len(r["family"]) == len(ids)
    assert r["n_families"] <= r["n_groups"] and max(r["family"]) + 1 == r["n_families"]
    # emboîtement : deux œuvres du même groupe sont dans la même famille
    fam_of = {}
    for g, f in zip(r["group"], r["family"]):
        assert fam_of.setdefault(g, f) == f
    assert c.get("/api/communities/inconnu").status_code == 404


def test_disagreements_find_planted_pair():
    from pixplot.analysis.disagreements import centiles, compute

    rng = np.random.default_rng(3)
    n = 400
    A = rng.normal(size=(n, 16)).astype(np.float32)
    B = rng.normal(size=(n, 16)).astype(np.float32)
    A[7] = A[3] + 0.01                     # 3 et 7 : jumelles selon A…
    B[7] = -B[3]                           # … opposées selon B
    A /= np.linalg.norm(A, axis=1, keepdims=True)
    B /= np.linalg.norm(B, axis=1, keepdims=True)
    ids = list(range(100, 100 + n))
    row = {i: i - 100 for i in ids}
    res = compute({"forme": (A, row), "sujet": (B, row)}, ids, k=5, max_rank=3, max_centile=0.2,
                  say=lambda m: None)
    top = res["pairs"]["forme>sujet"][0]
    assert {top["a"], top["b"]} == {103, 107} and top["rank"] == 1 and top["centile"] < 0.01
    assert all(p["centile"] < 0.2 for v in res["pairs"].values() for p in v)
    # centile : une œuvre identique à elle-même est au-dessus de tout l'échantillon
    assert centiles(B, np.array([0]), np.array([0]), np.arange(1, n))[0] == 1.0


def test_disagreements_and_pairs_api(env):
    s, data, c = env
    from pixplot.analysis import disagreements as D
    from pixplot.analysis.pairbench import load_space_matrix

    ids = [int(i) for i in data.ids]
    vec = {k: load_space_matrix(data.spaces, k, ids) for k in data.spaces.runs}
    D.save(data.analysis, D.compute(vec, ids, k=5, max_rank=3, max_centile=0.9, say=lambda m: None))
    data.__dict__.pop("_dis_cache", None)
    info = c.get("/api/info").json()
    combo = next(iter(info["disagreements"]))
    near, far = combo.split(">")
    r = c.get(f"/api/disagreements?near={near}&far={far}&limit=3").json()
    assert r["total"] == info["disagreements"][combo] and len(r["items"]) <= 3 and "label_a" in r["items"][0]
    assert c.get("/api/disagreements?near=forme&far=inconnu").status_code == 404
    a, b = ids[2], ids[3]
    c.post("/api/pairs", json={"a": a, "b": b, "type": "meme_sujet", "status": "proposée"})
    listed = c.get("/api/pairs").json()["pairs"]
    assert any(p["a"] == a and p["status"] == "proposée" and p["label_a"] for p in listed)
    c.post("/api/pairs", json={"a": a, "b": b, "type": "meme_sujet", "status": "validée"})
    assert c.get("/api/info").json()["annotated_pairs"].get("validée", 0) >= 1


def test_review_queue_decide_and_undo(env):
    s, data, c = env
    from pixplot.analysis import disagreements as D
    from pixplot.analysis.pairbench import Pair, add_pair, load_pairs, pairs_path
    from pixplot.analysis.pairbench import load_space_matrix
    from pixplot.analysis.review import load_log, log_path

    ids = [int(i) for i in data.ids]
    vec = {k: load_space_matrix(data.spaces, k, ids) for k in data.spaces.runs}
    D.save(data.analysis, D.compute(vec, ids, k=5, max_rank=3, max_centile=0.9, say=lambda m: None))
    path = pairs_path(s)
    a, b = ids[10], ids[11]
    add_pair(path, Pair(a, b, "filiation", "annotée", "proposée", "essai", ""))
    q = c.get("/api/review/queue?limit=5").json()
    first = q["items"][0]
    assert first["origin"] == "proposée" and {first["a"], first["b"]} == {a, b} and len(q["types"]) == 7
    assert any(x["origin"] == "désaccord" for x in q["items"])
    # valider en changeant de type, puis annuler : la paire proposée revient telle quelle
    body = {"a": a, "b": b, "decision": "valider", "type": "meme_sujet", "origin": "proposée",
            "proposed_type": "filiation", "source": "essai"}
    out = c.post("/api/review", json=body).json()
    assert out["stats"]["by_type"]["meme_sujet"] >= 1
    mine = [p for p in load_pairs(path) if {p.a, p.b} == {a, b}]
    assert [(p.type, p.status) for p in mine] == [("meme_sujet", "validée")]
    c.post("/api/review/undo", json=body)
    mine = [p for p in load_pairs(path) if {p.a, p.b} == {a, b}]
    assert [(p.type, p.status) for p in mine] == [("filiation", "proposée")]
    # une candidate « pas de lien » est notée au journal et ne revient plus
    cand = next(x for x in q["items"] if x["origin"] == "désaccord")
    rej = {"a": cand["a"], "b": cand["b"], "decision": "rejeter", "type": cand["type"], "origin": "désaccord",
           "source": cand["source"]}
    c.post("/api/review", json=rej)
    assert len(load_log(log_path(s))) == 1
    again = c.get("/api/review/queue?limit=200").json()["items"]
    assert not any({x["a"], x["b"]} == {cand["a"], cand["b"]} for x in again)
    c.post("/api/review/undo", json=rej)
    assert load_log(log_path(s)) == []
    assert c.post("/api/review", json={**rej, "decision": "effacer"}).status_code == 400


def test_zonebench_geometry_and_scores():
    from pixplot.analysis.zonebench import Region, _cells, dense_region_vectors, pointing, retrieval

    p = {"w": 1000, "h": 500}                 # paysage : bandes en haut et en bas du carré
    lb = (0, 168, 672, 336)                    # letterbox d'une image 1000×500 dans 672 px
    rows, cols = _cells((0, 0, 500, 250), p, (1000, 500), lb, 48, 672)   # quart haut gauche
    assert cols.min() == 0 and cols.max() == 23 and rows.min() == 12 and rows.max() == 23
    # cadre minuscule : au moins une zone
    r, c = _cells((10, 10, 11, 11), p, (1000, 500), lb, 48, 672)
    assert len(r) == 1 and len(c) == 1

    # grille synthétique : la zone du quart haut gauche porte un vecteur « cible »
    D = 8
    g = np.zeros((48, 48, D), dtype=np.float32)
    g[..., 0] = 1
    g[12:24, 0:24] = 0
    g[12:24, 0:24, 1] = 1
    grids = [(g, lb, (1000, 500))]
    paintings = [p]
    entities = [{"painting": 0, "boxes": [(0, 0, 500, 250)]}, {"painting": 0, "boxes": [(500, 250, 1000, 500)]}]
    regions = [Region(0, 0, (0, 0, 500, 250)), Region(0, 1, (500, 250, 1000, 500))]
    Q = np.eye(D, dtype=np.float32)[[1, 0]]   # requête 0 → cible, requête 1 → fond
    G = dense_region_vectors(grids, paintings, regions)
    rt = retrieval(Q, G, regions, entities)
    assert rt["R@1"] == 1.0 and rt["median_rank"] == 1
    pt = pointing(Q[:1], grids, paintings, entities[:1])
    assert pt["hit"] == 1.0 and 0.2 < pt["chance"] < 0.3   # un quart de l'œuvre


def test_corpus_report_and_regard_cards(env):
    from collections import Counter

    from pixplot.analysis.critique import CARDS, card, corpus_report, source_note

    s, data, c = env
    meta = {i: {"artist": "a" if i < 3 else "Unknown Artist", "style": "Ukiyo_e" if i == 0 else "Baroque"} for i in range(10)}
    r = corpus_report(meta, {"artist": Counter({"huggan/wikiart (Hugging Face)": 10})}, years=[None] * 10, places=0)
    assert r["coverage"]["artist"]["share"] == 0.3 and r["coverage"]["style"]["distinct"] == 2
    joined = " ".join(r["notes"])
    assert "artiste" in joined and "70 %" in joined and "Ukiyo_e" in joined and "10,0 %" in joined
    assert "chronologie est indisponible" in joined and "géographique est vide" in joined
    assert "bénévoles" in source_note("huggan/wikiart (Hugging Face)") and source_note("catalogue maison") == ""
    for key in ("forme", "sujet", "couleur", "touche"):
        assert set(CARDS[key]) >= {"model", "trained_on", "sees", "blind_to", "biases", "measured"}
    assert card("inconnu")["model"] == "inconnu"
    res = c.get("/api/corpus").json()
    assert res["report"]["n"] == len(data.ids) and all("card" in sp for sp in res["spaces"])


def test_gazetteer_and_typed_places(tmp_path):
    import sqlite3

    from pixplot.catalog import gazetteer
    from pixplot.catalog import places as P

    assert gazetteer.find_city("Munich, Germany") == "Munich" and gazetteer.find_city("Londres") == "London"
    assert gazetteer.find_institution_city("Yale Center for British Art") == "New Haven"
    assert gazetteer.find_city("Atlantide") is None
    assert P.norm_type("Exhibition") == "exposition" and P.norm_type("musée") == "conservation"
    with pytest.raises(ValueError):
        P.norm_type("cuisine")

    conn = sqlite3.connect(tmp_path / "c.sqlite")
    conn.executescript("CREATE TABLE artworks (id INTEGER PRIMARY KEY, path TEXT, status TEXT);")
    conn.executemany("INSERT INTO artworks VALUES (?, ?, 'ok')", [(1, str(tmp_path / "a.jpg")), (2, str(tmp_path / "b.jpg"))])
    meta = {1: {"repository": "Yale Center for British Art",
                "artist": "Walter Richard Sickert, born in Munich, Germany, 1860; active in England; died in Bathampton, England, 1942"},
            2: {"artist": "Anonyme", "place": "Atlantide"}}
    counts = P.derive_from_metadata(conn, meta)
    assert counts == {"conservation": 1, "naissance_artiste": 1, "deces_artiste": 1, "non_precise": 1}
    rows = {(r["artwork_id"], r["type"]): r for r in P.load_places(conn)}
    assert rows[(1, "naissance_artiste")]["year"] == 1860 and rows[(1, "naissance_artiste")]["lat"] == pytest.approx(48.137)
    assert rows[(1, "conservation")]["lon"] == pytest.approx(-72.928)
    assert rows[(2, "non_precise")]["lat"] is None                 # lieu inconnu : pas deviné

    f = tmp_path / "lieux.csv"
    f.write_text("path,type,place,lat,lon,date\nb.jpg,exposition,Salon de Paris,,,1874\n"
                 "b.jpg,creation,Atelier,43.3,5.4,1873\ninconnu.jpg,creation,Paris,,,\n", encoding="utf-8")
    r = P.import_places_csv(conn, f, source="essai")
    assert r == {"added": 2, "unmatched": 1, "no_coords": 0}       # « Salon de Paris » → Paris
    # une nouvelle déduction remplace les lieux déduits, garde ceux du fichier
    P.derive_from_metadata(conn, meta)
    assert sum(1 for x in P.load_places(conn) if x["source"] == "essai") == 2


def test_places_api(env):
    s, data, c = env
    from pixplot.catalog import db
    from pixplot.catalog.places import add_place, ensure

    conn = db.connect(s.catalog_path)
    ensure(conn)
    first, second = int(data.ids[0]), int(data.ids[1])
    add_place(conn, first, "creation", "Paris", date="1870")
    add_place(conn, first, "conservation", "Musée du Louvre", institution=True)
    add_place(conn, second, "represente", "Venise")
    conn.commit()
    conn.close()
    data.__dict__.pop("_place_counts", None)
    r = c.get("/api/places").json()
    keys = {t["key"] for t in r["types"]}
    assert {"creation", "conservation", "represente"} <= keys
    k = next(i for i, (row, t) in enumerate(zip(r["row"], r["type"])) if t == "creation" and row == data.row_of[first])
    assert r["year"][k] == 1870 and r["lat"][k] == pytest.approx(48.857)
    assert "creation" in c.get("/api/info").json()["places"]


def test_zone_boxes_and_index(tmp_path):
    pytest.importorskip("faiss")
    from pixplot.index.textzones import ZoneIndex, build_zone_index, crops, zone_boxes
    from pixplot.runs import create_run

    boxes = zone_boxes()
    assert len(boxes) == 20 and boxes[0] == (2, (0.0, 0.0, 0.5, 0.5)) and boxes[-1] == (4, (0.75, 0.75, 1.0, 1.0))
    parts = crops(Image.new("RGB", (400, 200)), boxes)
    assert parts[0].size == (200, 100) and parts[-1].size == (100, 50)

    # 30 œuvres × 20 zones aléatoires ; une zone « cible » plantée dans l'œuvre 7, case 13
    rng = np.random.default_rng(0)
    D = 64
    Z = rng.normal(size=(30, 20, D)).astype(np.float32)
    target = rng.normal(size=D).astype(np.float32)
    target /= np.linalg.norm(target)
    Z[7, 13] = target * 3
    Z /= np.linalg.norm(Z, axis=2, keepdims=True)
    zr = create_run("features", "zones_essai", {"encoder": "essai", "grids": [2, 4]}, runs_dir=tmp_path)
    np.save(zr.path / "ids.npy", np.arange(100, 130))
    np.save(zr.path / "zones.npy", Z.astype(np.float16))
    np.save(zr.path / "done.npy", np.ones(30, dtype=bool))
    zr.complete()
    run = build_zone_index(zr, runs_dir=tmp_path, pca_dim=16, say=lambda m: None)
    zi = ZoneIndex(run)
    hit = zi.search(target, k=3)[0]
    assert hit["id"] == 107 and hit["box"] == list(boxes[13][1]) and hit["grid"] == 4
    assert hit["score"] == pytest.approx(1.0, abs=2e-3)   # reclassement exact
    assert all(h["id"] != 107 for h in zi.search(target, k=3, allowed={100, 101, 102}))


def test_composition_layout_ranks(tmp_path):
    from pixplot.analysis.composition import layout, layout_ranks, layout_rows
    from pixplot.features.extract import OK

    rng = np.random.default_rng(1)
    n, D = 40, 8
    R = rng.normal(size=(n, 21, D)).astype(np.float16)
    R[7, 5:] = R[3, 5:] + np.float16(0.05) * rng.normal(size=(16, D)).astype(np.float16)  # même disposition
    R[7, :5] = rng.normal(size=(5, D))                                                    # mais autre ensemble
    np.save(tmp_path / "regions.npy", R)
    np.save(tmp_path / "ids.npy", np.arange(100, 100 + n))
    status = np.full(n, OK, dtype=np.int8)
    status[0] = OK + 1                                                     # une œuvre en échec : ignorée
    np.save(tmp_path / "status.npy", status)

    L = layout(R[[3, 7]])
    assert L.shape == (2, 16 * D) and np.allclose(np.linalg.norm(L, axis=1), 1, atol=1e-5)
    cells = R[[3, 7], 5:].astype(np.float32)
    cells /= np.linalg.norm(cells, axis=2, keepdims=True)
    assert np.isclose(L[0] @ L[1], (cells[0] * cells[1]).sum(axis=1).mean(), atol=1e-5)  # moyenne des 16 cosinus

    rows, row = layout_rows(tmp_path, list(range(100, 100 + n)))
    assert 100 not in row and len(rows) == n - 1
    ranks = layout_ranks(tmp_path, rows, np.array([row[103], row[107]]), np.array([row[107], row[103]]), chunk=7)
    assert ranks.tolist() == [1, 1]


def test_composition_common_cells():
    """Deux œuvres de même disposition mais de proportions différentes : la variante « cases
    communes » ne les pénalise pas pour les cases vides (bandes) de l'une d'elles."""
    from pixplot.analysis.composition import _cells, similarities

    rng = np.random.default_rng(2)
    R = rng.normal(size=(2, 21, 6)).astype(np.float32)
    R[1] = R[0]
    R[1, 17:21] = 0                                      # dernière rangée de cases : dans les bandes
    a, b = _cells(R[:1]), _cells(R[1:])
    blk = lambda c: (c[0].reshape(len(c[0]), -1), c[1])
    assert np.isclose(similarities("layout", blk(a), blk(b))[0, 0], 12 / 16)
    assert np.isclose(similarities("layout_communes", blk(a), blk(b))[0, 0], 1.0)


def test_correspondences_mutual_and_masked():
    """Les zones qui se répondent : correspondances mutuelles seulement, cases hors de l'œuvre
    exclues, cadres ramenés à l'image."""
    from pixplot.analysis.correspondences import cells_of, correspondences, match

    rng = np.random.default_rng(3)
    D = 16
    Ra = rng.normal(size=(21, D)).astype(np.float32)
    Rb = rng.normal(size=(21, D)).astype(np.float32)
    Rb[5 + 6] = Ra[5 + 1] * 2 + 0.01 * rng.normal(size=D)       # case 1 de A ↔ case 6 de B
    assert cells_of(Ra).shape == (16, D) and np.allclose(cells_of(Ra)[0], Ra[5])

    # deux œuvres carrées : toutes les cases sont sur l'œuvre
    m = correspondences(Ra, Rb, (1000, 1000), (1000, 1000), k=8)
    top = m[0]
    assert (top["cell_a"], top["cell_b"]) == (1, 6) and top["sim"] > 0.99
    assert top["box_a"] == [0.25, 0.0, 0.5, 0.25] and top["box_b"] == [0.5, 0.25, 0.75, 0.5]
    for x in m:                                                  # chaque paire est mutuelle
        S = cells_of(Ra) @ cells_of(Rb).T
        assert x["cell_b"] in np.argsort(-S[x["cell_a"]])[:16]

    # œuvre très large : la première rangée de cases tombe dans les bandes → jamais retenue
    boxes = [None] * 4 + [[0, 0, 1, 1]] * 12
    m = match(cells_of(Ra), cells_of(Ra), boxes, boxes, k=16)
    assert m and all(x["cell_a"] >= 4 and x["cell_b"] >= 4 for x in m)
    assert match(cells_of(Ra), cells_of(Rb), [None] * 16, boxes) == []

    # relecture par Antigravity : pas d'avertissement quand des rangées entières sont hors de l'œuvre,
    # et la moyenne de référence exclut la paire elle-même
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        m = match(cells_of(Ra), cells_of(Rb), boxes, boxes, k=16)
    A, B = cells_of(Ra), cells_of(Rb)
    S = (A / np.linalg.norm(A, axis=1, keepdims=True)) @ (B / np.linalg.norm(B, axis=1, keepdims=True)).T
    x = m[0]
    i, j, valid = x["cell_a"], x["cell_b"], list(range(4, 16))
    row = np.mean([S[i, c] for c in valid if c != j])
    col = np.mean([S[r, j] for r in valid if r != i])
    assert np.isclose(x["lift"], round(S[i, j] - max(row, col), 4), atol=1e-4)
    assert match(cells_of(Ra), cells_of(Rb), boxes, boxes, k=0) == []


def test_center_vectors_once(tmp_path):
    """Centrage (couleur, touche) : remplacé d'un coup, jamais refait à la reprise (audit Argon)."""
    from numpy.lib.format import open_memmap

    from pixplot.features.extract import FAILED, OK, center_vectors

    rng = np.random.default_rng(4)
    V = (rng.normal(size=(50, 8)) + 3).astype(np.float16)            # une forte composante commune
    g = open_memmap(tmp_path / "global.npy", "w+", np.float16, V.shape)
    g[:] = V
    g.flush()
    del g
    status = np.full(50, OK, dtype=np.int8)
    status[7] = FAILED
    assert center_vectors(tmp_path, status)
    once = np.load(tmp_path / "global.npy").astype(np.float32)
    ok = status == OK
    assert abs(once[ok].mean(axis=0)).max() < 0.2                    # moyenne retirée
    assert np.allclose(np.linalg.norm(once[ok], axis=1), 1, atol=1e-2)
    assert np.array_equal(once[7], V[7].astype(np.float32))          # ligne en échec intacte
    assert not (tmp_path / "global.centering.npy").exists()
    assert center_vectors(tmp_path, status)                          # reprise : rien ne change
    assert np.array_equal(np.load(tmp_path / "global.npy").astype(np.float32), once)


def test_neighbors_small_corpus():
    """Corpus plus petit que k : pas de -1 ni de -3,4e38 de FAISS gardés comme voisines."""
    pytest.importorskip("faiss")
    from pixplot.analysis.layout import neighbors

    X = np.eye(5, dtype=np.float32)
    rows, scores = neighbors(X, k=8)
    assert rows.shape == (5, 8)
    for i in range(5):
        real = rows[i][rows[i] >= 0]
        assert i not in real and len(real) == 4
        assert (scores[i][rows[i] < 0] == 0).all() and np.isfinite(scores[i]).all()
