"""Tests du banc d'occultation « Pourquoi ? » (pixplot whytest), sur corpus synthétique sans GPU."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from pixplot.analysis.pairbench import Pair
from pixplot.analysis.whytest import (
    center_cells_for,
    mask_canvas,
    prepare_image,
    run_whytest,
    sample_neighbor_pairs,
    summarize_records,
)
from pixplot.catalog.ingest import ingest
from pixplot.config import get_settings
from pixplot.encoders.base import EncodedBatch, Encoder, PAD_RGB
from pixplot.features.extract import extract
from pixplot.index.regions import cell_boxes


class _PatchDummyEncoder(Encoder):
    """Encodeur purement NumPy avec grille de patchs 4 × 4, pour tester whytest sans GPU."""

    name = "dinov3_dummy"
    dim = 12
    input_size = 64
    patch_size = 16

    def encode(self, batch: np.ndarray) -> EncodedBatch:
        # batch : (N, 3, 64, 64) → 4 × 4 patchs de 16 × 16 px
        n = batch.shape[0]
        patches = batch.reshape(n, 3, 4, 16, 4, 16).transpose(0, 2, 4, 1, 3, 5).reshape(n, 4, 4, 3, 256)
        mean_c = patches.mean(axis=-1)                          # (N, 4, 4, 3)
        std_c = patches.std(axis=-1)                            # (N, 4, 4, 3)
        q25 = np.percentile(patches, 25, axis=-1)               # (N, 4, 4, 3)
        q75 = np.percentile(patches, 75, axis=-1)               # (N, 4, 4, 3)
        grid = np.concatenate([mean_c, std_c, q25, q75], axis=-1).astype(np.float32)  # (N, 4, 4, 12)
        # Vecteur global : moyenne pondérée par l'énergie (les zones contrastées pèsent davantage)
        energy = (std_c.mean(axis=-1, keepdims=True) + 0.1).astype(np.float32)
        glob = (grid * energy).sum(axis=(1, 2)) / energy.sum(axis=(1, 2))
        glob /= np.maximum(np.linalg.norm(glob, axis=1, keepdims=True), 1e-12)
        return EncodedBatch(global_vectors=glob, patch_grid=grid)


def test_mask_canvas_preserves_letterbox_and_identity(tmp_path):
    """L'occultation ne touche pas aux bandes de letterbox et la couleur moyenne vient de l'œuvre."""
    # Image portrait très étroite (40 × 120) : bandes à gauche et à droite dans le carré 64 × 64
    arr = np.full((120, 40, 3), (20, 200, 40), dtype=np.uint8)
    p = tmp_path / "portrait.png"
    Image.fromarray(arr).save(p)

    prep = prepare_image(p, input_size=64, artwork_id=1)
    left, top, rw, rh = prep.box
    assert left > 0 and rw < 64
    assert tuple(prep.mean_rgb.tolist()) == (20, 200, 40)

    sq_boxes = [b for _, b in cell_boxes((4,), 4)]
    enc = _PatchDummyEncoder()
    ref_arr, _ = enc.preprocess(Image.open(p).convert("RGB"))
    unmasked, area0 = mask_canvas(prep, [], sq_boxes, fill="mean")
    assert area0 == 0.0
    assert np.allclose(unmasked, ref_arr, atol=1e-6)

    for fill in ("mean", "blur"):
        masked, area = mask_canvas(prep, [5, 6, 9, 10], sq_boxes, fill=fill, blur_radius=6)
        assert 0.2 < area <= 1.0
        # Les bandes de letterbox à gauche (colonne 0) restent strictement à PAD_RGB
        expected_pad = (np.array(PAD_RGB, dtype=np.float32) / 255.0 - np.array([0.485, 0.456, 0.406])) / np.array([0.229, 0.224, 0.225])
        assert np.allclose(masked[:, :, 0], expected_pad[:, None], atol=1e-4)


def test_whytest_end_to_end_and_resume(tmp_path):
    """Exécution complète sur petit corpus synthétique (mean + blur, reprise, planche, vérification)."""
    images = tmp_path / "images"
    images.mkdir()
    rng = np.random.default_rng(7)

    # 20 images 64 × 64 (10 paires de motifs localisés) : 4 paires validées, le reste disponible pour les témoins
    for i in range(20):
        bg = rng.integers(90, 140, size=(64, 64, 3), dtype=np.uint8)
        grp = i // 2
        cols = [((grp * 53 + c * 61) % 220 + 20, (grp * 97 + c * 37) % 220 + 20, (grp * 31 + c * 83) % 220 + 20)
                for c in range(4)]
        positions = [(0, 0), (0, 3), (3, 0), (3, 3)] if grp % 2 == 0 else [(0, 1), (1, 3), (2, 0), (3, 2)]
        for (gy, gx), col in zip(positions, cols):
            patch = np.tile(np.array(col, dtype=np.uint8), (16, 16, 1))
            patch[::2, ::2] = 255 - patch[::2, ::2]
            bg[gy * 16:(gy + 1) * 16, gx * 16:(gx + 1) * 16] = patch
        Image.fromarray(bg).save(images / f"img_{i:02d}.png")

    s = get_settings(tmp_path / "data")
    ingest([images], s.catalog_path, s.thumbs_dir, workers=1)
    enc = _PatchDummyEncoder()
    run = extract(enc, s.catalog_path, s.runs_dir, batch_size=8, workers=1)

    pairs = [Pair(1 + 2 * k, 2 + 2 * k, "meme_composition", "annotée", "validée") for k in range(4)]
    logs: list[str] = []
    rep = run_whytest(
        s, run, pairs, encoder=enc, k=4, n_random=5, seed=0, fills=("mean", "blur"),
        batch_size=16, n_boot=200, blur_radius=6, resume=True, make_sheet=True, say=logs.append,
    )

    assert rep["verification"]["ok"] is True
    assert rep["verification"]["max_abs_cos_diff"] < 0.01
    assert rep["counts"]["validees"]["total"] == 4
    assert rep["counts"]["validees"]["ge_k"] == 4
    assert rep["counts"]["voisines"]["total"] == 4
    assert (s.data_dir / "bench" / "whytest_report.json").exists()
    assert rep["sheet"]["path"] and Path(rep["sheet"]["path"]).exists()

    for fill in ("mean", "blur"):
        st = rep["results"][fill]["groups"]["validees"]["both"]
        assert st["n_pairs"] == rep["counts"]["validees"]["ge_k"]
        assert "median_ci" in st["a_why"] and len(st["a_why"]["median_ci"]) == 2
        assert "p_median" in st["diff_a_minus_b"]
        assert "criterion" in st

    # Reprise : aucune nouvelle image d'occultation ne doit être réencodée
    rep2 = run_whytest(
        s, run, pairs, encoder=enc, k=4, n_random=5, seed=0, fills=("mean", "blur"),
        batch_size=16, n_boot=200, blur_radius=6, resume=True, make_sheet=False, say=lambda _: None,
    )
    assert rep2["total_images_encoded"] == rep2["verification"]["n_unique_artworks"]
    assert rep2["results"]["mean"]["groups"]["validees"]["both"]["a_why"]["median"] == (
        rep["results"]["mean"]["groups"]["validees"]["both"]["a_why"]["median"]
    )


def test_whytest_verification_fails_on_mismatch(tmp_path):
    """Si les vecteurs du run ne correspondent pas au réencodage (écart >= 0,01), on s'arrête net."""
    import pytest

    images = tmp_path / "images"
    images.mkdir()
    rng = np.random.default_rng(1)
    for i in range(6):
        Image.fromarray(rng.integers(0, 255, (64, 64, 3), dtype=np.uint8)).save(images / f"x_{i}.png")

    s = get_settings(tmp_path / "data")
    ingest([images], s.catalog_path, s.thumbs_dir, workers=1)
    enc = _PatchDummyEncoder()
    run = extract(enc, s.catalog_path, s.runs_dir, batch_size=6, workers=1)

    # Corrompt global.npy pour simuler un décalage de prétraitement
    g_path = run.path / "global.npy"
    g = np.load(g_path).copy()
    g[:] = -g
    np.save(g_path, g)

    pairs = [Pair(1, 2, "meme_composition", "annotée", "validée")]
    with pytest.raises(RuntimeError, match="prétraitement"):
        run_whytest(s, run, pairs, encoder=enc, k=4, n_random=2, fills=("mean",),
                    n_boot=50, make_sheet=False, say=lambda _: None)


def test_helpers_and_cli_parser():
    """Vérifie center_cells_for, sample_neighbor_pairs, summarize_records et le parseur CLI."""
    from pixplot.cli import build_parser

    sq = [b for _, b in cell_boxes((4,), 28)]
    assert center_cells_for(list(range(16)), sq, k=4) == [5, 6, 9, 10]
    assert len(center_cells_for([0, 1, 2, 3, 4, 5], sq, k=4)) == 4

    X = np.eye(6, dtype=np.float32)
    X[0, 1] = X[1, 0] = 0.8
    X /= np.linalg.norm(X, axis=1, keepdims=True)
    nbrs = sample_neighbor_pairs(np.arange(1, 7), X, n=2, seed=0)
    assert len(nbrs) == 2 and all(p.a != p.b for p in nbrs)

    recs = [
        {"cos_orig": 0.8, "both": {"drop_a": 0.30, "drop_b": 0.05, "drop_c": 0.06},
         "one": {"drop_a": 0.15, "drop_b": 0.03, "drop_c": 0.03},
         "areas": {"a": {"area_a": 0.25, "area_both": 0.25}, "b": {"area_a": 0.25, "area_both": 0.25},
                   "c": {"area_a": 0.25, "area_both": 0.25}}}
        for _ in range(10)
    ]
    st = summarize_records(recs, "both", n_boot=200, seed=0)
    assert st["criterion"]["passed"] is True
    assert st["diff_a_minus_b"]["ratio_median"] == 6.0

    args = build_parser().parse_args(["whytest", "--fills", "mean", "--random", "5", "--no-sheet"])
    assert args.command == "whytest" and args.fills == "mean" and args.random == 5 and args.no_sheet is True
