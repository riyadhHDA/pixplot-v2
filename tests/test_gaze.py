"""Tests unitaires et bout-en-bout pour l'évaluation oculométrique (AVAtt, ``pixplot/analysis/gaze.py``)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
from PIL import Image

from pixplot.analysis.gaze import (
    AvattPainting,
    bootstrap_paired,
    bootstrap_summary,
    boxes_metrics,
    center_bias_map,
    evaluate_search_zones,
    evaluate_why,
    load_avatt,
    local_contrast_map,
    map_nss,
    match_avatt_to_catalog,
    render_contact_sheet,
    top_k_cells_from_map,
)
from pixplot.index.textzones import ZoneIndex, zone_boxes
from pixplot.runs import create_run


def test_boxes_metrics_and_nss_identities():
    # Fixations concentrées uniquement dans le quart supérieur gauche [0, 0, 0.5, 0.5]
    fix = np.array([[0.1, 0.1], [0.2, 0.2], [0.3, 0.3], [0.4, 0.4]], dtype=np.float32)
    m_hit = boxes_metrics(fix, [[0.0, 0.0, 0.5, 0.5]])
    assert abs(m_hit["fix_share"] - 1.0) < 1e-6
    assert abs(m_hit["area"] - 0.25) < 1e-3
    assert abs(m_hit["enrichment"] - 4.0) < 0.05
    # NSS binaire exact : (1 - 0.25) / sqrt(0.25 * 0.75) = sqrt(3) ≈ 1.7321
    assert abs(m_hit["nss"] - np.sqrt(3.0)) < 0.02

    # Fixations dans une zone vide → fix_share = 0, NSS = -0.25 / sqrt(0.25 * 0.75) = -1/sqrt(3)
    m_miss = boxes_metrics(fix, [[0.5, 0.5, 1.0, 1.0]])
    assert m_miss["fix_share"] == 0.0
    assert abs(m_miss["nss"] + 1.0 / np.sqrt(3.0)) < 0.02


def test_naive_baselines_center_and_contrast():
    cmap = center_bias_map(64, sigma=0.25)
    assert cmap.shape == (64, 64)
    center_fix = np.array([[0.5, 0.5], [0.48, 0.52]], dtype=np.float32)
    corner_fix = np.array([[0.02, 0.02], [0.98, 0.98]], dtype=np.float32)
    assert map_nss(cmap, center_fix) > 1.0
    assert map_nss(cmap, corner_fix) < -1.0

    # Image grise uniforme avec un carré blanc très contrasté en bas à droite
    arr = np.full((128, 128, 3), 120, dtype=np.uint8)
    arr[80:115, 80:115] = 250
    lmap = local_contrast_map(Image.fromarray(arr), size=64)
    grid_2x2 = {i: list(b) for i, (_, b) in enumerate(zone_boxes((2,)))}
    best = top_k_cells_from_map(lmap, grid_2x2, 1)
    assert best == [3]  # case bas-droite


def test_bootstrap_summary_and_paired():
    a = np.array([0.8, 0.9, 0.7, 0.85, 0.95, 0.82], dtype=np.float64)
    b = np.array([0.2, 0.3, 0.25, 0.15, 0.3, 0.22], dtype=np.float64)
    s = bootstrap_summary(a, n_boot=400, seed=0)
    assert s["n"] == 6
    assert s["mean_ci"][0] <= s["mean"] <= s["mean_ci"][1]
    p = bootstrap_paired(a, b, n_boot=400, seed=0)
    assert p["mean_diff"] > 0.5
    assert p["mean_ci"][0] > 0.0
    assert p["p_mean"] < 0.05
    assert p["share_pos"] == 1.0


def _make_mini_avatt(tmp_path: Path, source_images: list[Path]) -> Path:
    """Construit un mini jeu AVAtt (stimuli sur fond gris, metadata.csv, scanpaths) à partir d'images réelles."""
    avatt = tmp_path / "mini_avatt"
    (avatt / "images").mkdir(parents=True)
    (avatt / "scanpaths").mkdir(parents=True)

    rows = []
    for idx, src in enumerate(source_images, start=1):
        iid = f"avatt_{idx:04d}"
        im = Image.open(src).convert("RGB")
        # Pose l'image au centre d'un cadre gris 300 × 200
        canvas = Image.new("RGB", (300, 200), (170, 170, 170))
        w, h = im.size
        x0, y0 = (300 - w) // 2, (200 - h) // 2
        canvas.paste(im, (x0, y0))
        canvas.save(avatt / "images" / f"{iid}.jpg", quality=95)

        # Fixations concentrées au centre de la peinture + 1 fixation hors cadre (doit être filtrée)
        cx, cy = x0 + w * 0.5, y0 + h * 0.5
        fixs = [
            {"x": cx + dx, "y": cy + dy, "onset_ms": 100 * k, "duration_ms": 250, "distance_mm": 600.0}
            for k, (dx, dy) in enumerate([(-5, -5), (0, 0), (5, 5), (-3, 4), (4, -3)])
        ] + [{"x": 2, "y": 2, "onset_ms": 900, "duration_ms": 100, "distance_mm": 600.0}]
        (avatt / "scanpaths" / f"{iid}.jsonl").write_text(
            json.dumps({"observer": 1, "fixations": fixs}) + "\n", encoding="utf-8"
        )
        rows.append({
            "image_id": iid,
            "title": f"Peinture {idx}",
            "artist": f"Artiste {idx}",
            "year": "1880",
            "movement": "Impressionism",
            "genre": "landscape",
            "copyright_status": "public domain",
            "exposure_s": "15.0",
            "n_observers": "1",
            "n_fixations": str(len(fixs)),
            "painting_x0": str(x0),
            "painting_y0": str(y0),
            "painting_x1": str(x0 + w),
            "painting_y1": str(y0 + h),
            "duplicate_of": "",
        })

    # Ajoute une ligne doublon qui doit être exclue par défaut
    dup = dict(rows[0], image_id="avatt_9999", duplicate_of=rows[0]["image_id"])
    rows.append(dup)

    with open(avatt / "metadata.csv", "w", encoding="utf-8", newline="") as f:
        w_csv = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w_csv.writeheader()
        w_csv.writerows(rows)
    return avatt


def test_end_to_end_on_synthetic_corpus(atlas_env, tmp_path):
    """Vérifie le chargement AVAtt, le rattachement dHash, « Pourquoi ? » et `search_zones` sur ``atlas_env``."""
    import sqlite3

    s, _ = atlas_env
    conn = sqlite3.connect(s.catalog_path)
    img_rows = conn.execute("SELECT id, path FROM artworks WHERE status = 'ok' ORDER BY id LIMIT 6").fetchall()
    conn.close()
    src_paths = [Path(r[1]) for r in img_rows]
    avatt_dir = _make_mini_avatt(tmp_path, src_paths)

    paintings, load_info = load_avatt(avatt_dir)
    assert load_info["rows_total"] == 7
    assert load_info["duplicates_excluded"] == 1
    assert load_info["paintings_loaded"] == 6
    assert all(len(p.fixations) == 5 for p in paintings)  # la fixation hors cadre est bien filtrée

    # Rattachement dHash (relaxé sur ce corpus synthétique quasi-uniforme par artiste)
    match_info = match_avatt_to_catalog(paintings, s.catalog_path, max_bits=16, min_margin=0)
    assert match_info["matched"] >= 3

    # Crée un run synthétique de vecteurs avec régions 4 × 4 (1 + 4 + 16 = 21 zones)
    rng = np.random.default_rng(7)
    conn = sqlite3.connect(s.catalog_path)
    all_ids = np.array([r[0] for r in conn.execute("SELECT id FROM artworks WHERE status = 'ok' ORDER BY id")], dtype=np.int64)
    conn.close()
    n, d = len(all_ids), 16
    G = rng.normal(size=(n, d)).astype(np.float32)
    G /= np.linalg.norm(G, axis=1, keepdims=True)
    R = rng.normal(size=(n, 21, d)).astype(np.float32)
    R /= np.linalg.norm(R, axis=2, keepdims=True)

    run_dir = tmp_path / "runs"
    feat_run = create_run(
        "features", "dinov3_vitb16",
        {"encoder": "dinov3_vitb16", "region_grids": [1, 2, 4], "input_size": 224, "patch_size": 16},
        runs_dir=run_dir,
    )
    np.save(feat_run.path / "ids.npy", all_ids)
    np.save(feat_run.path / "status.npy", np.ones(n, dtype=np.uint8))
    np.save(feat_run.path / "global.npy", G)
    np.save(feat_run.path / "regions.npy", R)
    feat_run.complete(count=n)

    res_why = evaluate_why(paintings, s.catalog_path, run_dir, neighbor_pool="avatt", n_random=10, n_boot=200, seed=0, say=lambda _: None)
    assert res_why["n_paintings"] >= 1
    assert "why" in res_why["conditions"]
    assert "center" in res_why["conditions"]
    assert "contrast" in res_why["conditions"]
    assert "why_minus_random" in res_why["paired"]
    assert "why_minus_center" in res_why["paired"]

    # Planche contact visuelle
    sheet = render_contact_sheet([(paintings[0], [[0.25, 0.25, 0.75, 0.75]], "test")], tmp_path / "sheet.jpg", cols=1)
    assert sheet.exists()

    # Crée un mini index textzones (20 zones par œuvre) et teste evaluate_search_zones avec un encodeur factice
    import faiss

    z_feat = create_run("features", "zones_siglip2", {"encoder": "siglip2", "grids": [2, 4]}, runs_dir=run_dir)
    Z_arr = rng.normal(size=(n, 20, d)).astype(np.float32)
    Z_arr /= np.linalg.norm(Z_arr, axis=2, keepdims=True)
    np.save(z_feat.path / "ids.npy", all_ids)
    np.save(z_feat.path / "zones.npy", Z_arr.astype(np.float16))
    np.save(z_feat.path / "done.npy", np.ones(n, dtype=bool))
    z_feat.complete(artworks=n, zones=n * 20)

    z_idx = create_run("index", "textzones_siglip2", {"grids": [2, 4], "pca_dim": d}, parent=z_feat, runs_dir=run_dir)
    index = faiss.IndexFlatIP(d)
    index.add(Z_arr.reshape(-1, d))
    faiss.write_index(index, str(z_idx.path / "zones.faiss"))
    np.save(z_idx.path / "zone_ids.npy", np.repeat(all_ids, 20))
    np.save(z_idx.path / "zone_cells.npy", np.tile(np.arange(20, dtype=np.int16), n))
    np.save(z_idx.path / "zone_rows.npy", np.repeat(np.arange(n, dtype=np.int64), 20))
    np.save(z_idx.path / "pca_mean.npy", np.zeros(d, dtype=np.float32))
    np.save(z_idx.path / "pca_components.npy", np.eye(d, dtype=np.float32))
    z_idx.complete(count=n * 20, artworks=n)

    class _DummyEncoder:
        def encode_text(self, texts: list[str]) -> np.ndarray:
            v = rng.normal(size=(len(texts), d)).astype(np.float32)
            return v / np.linalg.norm(v, axis=1, keepdims=True)

    res_z = evaluate_search_zones(
        paintings, run_dir, queries=("visage", "arbre"), top_k_per_query=3,
        encoder=_DummyEncoder(), n_boot=200, seed=0, say=lambda _: None,
    )
    assert res_z["iconographic_queries"]["n_paintings"] >= 1
    assert res_z["title_queries"]["n_paintings"] >= 1
    assert "zone_minus_random" in res_z["iconographic_queries"]["paired"]
    assert "zone_minus_center" in res_z["iconographic_queries"]["paired"]
