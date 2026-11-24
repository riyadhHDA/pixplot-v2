"""Tests de la pyramide de tuiles précalculées (CPU, reprise, CLI, API et formats)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from pixplot.analysis.tiles import build_tiles, find_tiles_run, tile_path
from pixplot.api.app import create_app
from pixplot.api.data import AtlasData
from pixplot.cli import main as cli_main
from pixplot.config import get_settings
from pixplot.runs import latest_run


def _isolated_settings(atlas_env, tmp_path: Path):
    """Copie légère de ``atlas_env`` (catalogue, vignettes, runs) pour isoler les tests de tuiles."""
    s_src, n = atlas_env
    dst = tmp_path / "data"
    dst.mkdir()
    shutil.copy2(s_src.catalog_path, dst / "catalog.sqlite")
    shutil.copytree(s_src.thumbs_dir, dst / "thumbs")
    shutil.copytree(s_src.runs_dir, dst / "runs")
    return get_settings(dst), n


def test_build_tiles_and_resume(atlas_env, tmp_path):
    s, n = _isolated_settings(atlas_env, tmp_path)
    ana = latest_run("analysis", runs_dir=s.runs_dir)
    assert find_tiles_run(ana, s.runs_dir) is None

    log_file = s.data_dir / "tiles.log"
    run = build_tiles(ana, s.thumbs_dir, s.runs_dir, max_level=2, tile_size=128, log_path=log_file)
    assert run.manifest["stage"] == "tiles"
    assert run.manifest["parent"] == ana.id
    assert run.manifest["status"] == "complete"
    assert find_tiles_run(ana, s.runs_dir).id == run.id
    assert log_file.exists() and "Terminé" in log_file.read_text(encoding="utf-8")

    meta = json.loads((run.path / "tiles.json").read_text(encoding="utf-8"))
    assert meta["count"] == n
    assert meta["tile_size"] == 128
    assert meta["max_level"] == 2
    assert meta["format"] == "webp"
    assert meta["levels"]["0"] == ["0/0"]
    root_tile = tile_path(run.path, 0, 0, 0, "webp")
    assert root_tile.exists()
    with Image.open(root_tile) as im:
        assert im.size == (128, 128)

    # Simulation d'une interruption : on supprime une tuile et on repasse le run en "running".
    root_tile.unlink()
    run.manifest["status"] = "running"
    run.save()

    resumed = build_tiles(ana, s.thumbs_dir, s.runs_dir, max_level=2, tile_size=128, resume=True, log_path=log_file)
    assert resumed.path == run.path
    assert resumed.manifest["status"] == "complete"
    assert resumed.manifest["outputs"]["resumed"] is True
    assert resumed.manifest["outputs"]["skipped_tiles"] >= 1
    assert root_tile.exists()


def test_cli_and_api_tiles(atlas_env, tmp_path):
    s, n = _isolated_settings(atlas_env, tmp_path)

    # Avant calcul : /api/info annonce tiles=False et /api/tiles renvoie 404.
    client_before = TestClient(create_app(AtlasData.load(s)))
    assert client_before.get("/api/info").json()["tiles"] is False
    assert client_before.get("/api/tiles").status_code == 404

    # Calcul par la commande CLI `pixplot tiles`.
    rc = cli_main(["--data", str(s.data_dir), "tiles", "--max-level", "2", "--tile-size", "128"])
    assert rc == 0

    # Après calcul : /api/info, /api/tiles et /api/tiles/0/0/0.webp répondent.
    client = TestClient(create_app(AtlasData.load(s)))
    assert client.get("/api/info").json()["tiles"] is True

    r_meta = client.get("/api/tiles")
    assert r_meta.status_code == 200
    meta = r_meta.json()
    assert meta["count"] == n and meta["max_level"] == 2

    r_img = client.get("/api/tiles/0/0/0.webp")
    assert r_img.status_code == 200
    assert r_img.headers["content-type"] == "image/webp"
    assert len(r_img.content) > 100

    # Tuile inexistante ou extension inconnue → 404.
    assert client.get("/api/tiles/9/0/0.webp").status_code == 404
    assert client.get("/api/tiles/0/0/0.gif").status_code == 404
