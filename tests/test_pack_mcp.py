"""Étape 6 : Research Pack et serveur MCP."""

import asyncio
import csv
import io
import json
import zipfile

import pytest

from pixplot.api.data import AtlasData
from pixplot.export import selection as sel
from pixplot.export.pack import build_pack


@pytest.fixture(scope="module")
def data(atlas_env):
    s, _ = atlas_env
    return AtlasData.load(s)


def test_research_pack(data, tmp_path):
    chosen = sel.by_similar(data, int(data.ids[0]), k=5)
    first = chosen.ids[0]
    path = build_pack(data, chosen.ids, tmp_path, "Rouges et voisines", question="Pourquoi ces rouges ?",
                      selection=chosen.how, scores=chosen.scores, details={first: [0, 0, 0.5, 0.5]})
    z = zipfile.ZipFile(path)
    names = set(z.namelist())
    assert {"manifest.json", "summary.md", "artworks.csv", "relations.csv"} <= names
    assert {f"evidence/{i}.jpg" for i in chosen.ids} <= names and f"evidence/detail_{first}.jpg" in names
    manifest = json.loads(z.read("manifest.json"))
    assert manifest["artwork_ids"] == chosen.ids and manifest["question"] == "Pourquoi ces rouges ?"
    assert manifest["runs"]["features"] == data.features.id and manifest["caveats"]
    rows = list(csv.DictReader(io.StringIO(z.read("artworks.csv").decode())))
    assert len(rows) == 6 and rows[0]["artist"] and rows[0]["image"].startswith("evidence/")
    rel = list(csv.DictReader(io.StringIO(z.read("relations.csv").decode())))
    assert len(rel) == 6 * 5 // 2
    summary = z.read("summary.md").decode()
    assert "Pourquoi ces rouges ?" in summary and "pas une preuve" in summary
    assert path.stat().st_size < 2 * 2**20


def test_selections(data):
    g = sel.by_cluster(data, 1)
    assert len(g.ids) == int((data.clusters == 0).sum())
    assert sel.by_ids(data, [int(data.ids[0]), 999999]).ids == [int(data.ids[0])]
    with pytest.raises(ValueError):
        sel.by_cluster(data, 99)


def test_api_pack(data):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from pixplot.api.app import create_app

    c = TestClient(create_app(data))
    ids = [int(i) for i in data.ids[:4]]
    r = c.post("/api/pack", json={"ids": ids, "title": "Essai", "question": "Q ?"})
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert "manifest.json" in zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert c.post("/api/pack", json={"ids": [999999]}).status_code == 400


def test_mcp_tools(data):
    pytest.importorskip("mcp")
    from pixplot.mcp.server import create_server

    srv = create_server(data)
    first = int(data.ids[0])

    async def call(name, args):
        return await srv.call_tool(name, args)

    async def scenario():
        tools = {t.name for t in await srv.list_tools()}
        assert tools == {"corpus_overview", "search_by_text", "similar_artworks", "search_detail", "search_zones", "get_artwork",
                         "view_artwork", "view_detail", "compare_artworks", "get_group", "find_atypical",
                         "export_research_pack", "check_labels", "notebook_add", "notebook_list", "why_similar"}
        why = await call("why_similar", {"artwork_a": first, "artwork_b": int(data.ids[1])})
        assert "zone" in why.content[0].text and why.content[1].type == "image"
        overview = json.loads((await call("corpus_overview", {})).content[0].text)
        assert overview["count"] == len(data.ids) and len(overview["groups"]) == 3
        art = json.loads((await call("get_artwork", {"artwork_id": first})).content[0].text)
        assert art["id"] == first and len(art["neighbors"]) == 5
        img = await call("view_artwork", {"artwork_id": first, "size": 256})
        assert [c.type for c in img.content] == ["text", "image"]
        det = await call("view_detail", {"artwork_id": first, "x0": 0, "y0": 0, "x1": 0.5, "y1": 0.5})
        assert det.content[1].type == "image"
        cmp = await call("compare_artworks", {"artwork_ids": [int(i) for i in data.ids[:3]]})
        assert [c.type for c in cmp.content] == ["text", "image", "text"]
        group = json.loads((await call("get_group", {"group_number": 1, "k": 3})).content[0].text)
        assert len(group["artworks"]) == 3
        sim = json.loads((await call("similar_artworks", {"artwork_id": first, "k": 4, "space": "couleur"})).content[0].text)
        assert sim["space"] == "couleur" and len(sim["neighbors"]) == 4
        note = json.loads((await call("notebook_add", {"title": "Piste", "note": "vu / calculé / supposé",
                                                        "artwork_ids": [first]})).content[0].text)
        assert note["artwork_ids"] == [first] and note["context"]["auteur"].startswith("assistant")
        listed = json.loads((await call("notebook_list", {"query": "Piste"})).content[0].text)
        assert listed["entries"][0]["id"] == note["id"]
        atyp = json.loads((await call("find_atypical", {"k": 2})).content[0].text)
        assert len(atyp["artworks"]) == 2
        text = json.loads((await call("search_by_text", {"query": "un chat"})).content[0].text)
        assert "error" in text  # pas de vecteurs SigLIP dans ce corpus de test
        pack = json.loads((await call("export_research_pack",
                                      {"artwork_ids": [int(i) for i in data.ids[:3]], "title": "MCP"})).content[0].text)
        assert pack["artworks"] == 3 and pack["path"].endswith(".zip")
        # Appelé directement, un outil en échec lève une exception ; à travers le transport
        # MCP (stdio), le client reçoit une réponse marquée is_error.
        with pytest.raises(Exception, match="get_artwork") as err:
            await call("get_artwork", {"artwork_id": 999999})
        assert "inconnue" in str(err.value.__cause__)

    asyncio.run(scenario())


def test_antigravity_relay(tmp_path, monkeypatch):
    """Relais vers Antigravity : agy trouvé à l'emplacement Windows, lancé en lecture seule."""
    from pixplot.mcp import antigravity as ag

    # emplacement de l'installateur Windows : %LOCALAPPDATA%\agy\bin\agy.exe
    exe = tmp_path / "agy" / "bin" / "agy.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    assert ag.find_agy({"LOCALAPPDATA": str(tmp_path), "PATH": ""}) == str(exe)
    assert ag.find_agy({"PATH": ""}) is None
    # installé par winget : dossier des paquets, pas encore dans le PATH de la session
    wg = tmp_path / "w" / "Microsoft" / "WinGet" / "Packages" / "Google.AntigravityCLI_x" / "agy.exe"
    wg.parent.mkdir(parents=True)
    wg.write_bytes(b"")
    assert ag.find_agy({"LOCALAPPDATA": str(tmp_path / "w"), "PATH": ""}) == str(wg)
    assert ag.find_agy({"AGY_BIN": str(tmp_path / "absent")}) is None

    f = tmp_path / "a.py"
    f.write_text("x = 1")
    args = ag.build_args("agy", "Relis ce code", [str(f), str(tmp_path), str(tmp_path / "absent")], model="m")
    assert args[:2] == ["agy", "-p"] and "--dangerously-skip-permissions" not in args
    assert args[args.index("--mode") + 1] == "plan" and "--sandbox" in args and args[args.index("--model") + 1] == "m"
    assert args.count("--add-dir") == 1 and args[args.index("--add-dir") + 1] == str(tmp_path)  # dossiers dédoublonnés
    assert "ne modifie aucun fichier" in args[2] and "absent" not in args[2] and args[2].endswith("Relis ce code")

    calls = []

    class R:
        returncode, stdout, stderr = 0, "Deux remarques…", ""

    monkeypatch.setenv("AGY_BIN", str(exe))
    monkeypatch.setattr(ag.subprocess, "run", lambda a, **kw: calls.append(a) or R())
    assert ag.ask("Avis ?") == (True, "Deux remarques…") and calls[0][0] == str(exe)
    monkeypatch.setenv("AGY_BIN", str(tmp_path / "absent"))
    ok, text = ag.ask("Avis ?")
    assert not ok and "install.ps1" in text


def test_antigravity_server_tools():
    pytest.importorskip("mcp")
    from pixplot.mcp.antigravity import create_server

    tools = asyncio.run(create_server().list_tools())
    assert [t.name for t in tools] == ["ask_antigravity"]
