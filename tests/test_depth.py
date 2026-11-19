"""Tests de l'encodeur Depth Anything V2 (profondeur) sur le petit corpus synthétique."""

from __future__ import annotations

import json
import shutil

import numpy as np
import pytest

from pixplot.analysis.pairbench import Pair, add_pair, pairs_path
from pixplot.api.data import AtlasData
from pixplot.api.spaces import NOT_KEPT, Spaces, describe_encoder
from pixplot.cli import main as cli_main
from pixplot.config import get_settings
from pixplot.encoders.base import EncodedBatch, Encoder
from pixplot.encoders.depth import depth_grid_descriptor
from pixplot.encoders.registry import ENCODERS, get_encoder
from pixplot.features.extract import extract
from pixplot.features.store import FeatureStore


def test_depth_grid_descriptor_invariances_no_torch():
    """Le descripteur 8 × 8 ignore les bandes letterbox, est invariant aux transformations affines
    et gère les cartes planes ou très allongées sans PyTorch."""
    rng = np.random.default_rng(42)
    artwork = rng.uniform(0.0, 1.0, size=(60, 100)).astype(np.float32)

    # Œuvre placée au centre d'un carré 100×100 avec bandes haute/basse polluées
    canvas = np.full((100, 100), 9999.0, dtype=np.float32)
    canvas[20:80, 0:100] = artwork
    box = (0, 20, 100, 60)

    v_crop = depth_grid_descriptor(canvas, box=box, input_size=100, grid=8)
    v_direct = depth_grid_descriptor(artwork, box=None, input_size=100, grid=8)
    assert v_crop.shape == (64,)
    assert np.isclose(np.linalg.norm(v_crop), 1.0, atol=1e-5)
    assert np.isclose(v_crop.mean(), 0.0, atol=1e-5)
    assert np.allclose(v_crop, v_direct, atol=1e-5)

    # Invariance affine (a * d + b, a > 0)
    v_affine = depth_grid_descriptor(artwork * 4.5 + 17.2, box=None, input_size=100, grid=8)
    assert np.allclose(v_direct, v_affine, atol=1e-5)

    # Carte complètement plate : vecteur nul, pas de NaN
    v_flat = depth_grid_descriptor(np.full((32, 32), 3.14, dtype=np.float32), grid=8)
    assert np.all(v_flat == 0.0) and np.all(np.isfinite(v_flat))

    # Format très allongé (hauteur < 8 pixels dans le letterbox)
    thin = np.linspace(0.0, 1.0, 3 * 64, dtype=np.float32).reshape(3, 64)
    v_thin = depth_grid_descriptor(thin, grid=8)
    assert v_thin.shape == (64,) and np.all(np.isfinite(v_thin))


class _FakeDepth(Encoder):
    """Encodeur léger sans PyTorch, au nom ``depth_anything_v2_small``, vérifiant le passage des boîtes."""

    name = "depth_anything_v2_small"
    dim = 64
    input_size = 112
    patch_size = None
    needs_boxes = True

    def __init__(self):
        self.seen_boxes: list[tuple[int, int, int, int]] = []

    def encode(self, batch: np.ndarray, boxes=None) -> EncodedBatch:
        assert boxes is not None and len(boxes) == len(batch)
        self.seen_boxes.extend(boxes)
        vecs = []
        for img, box in zip(batch, boxes):
            # Utilise la luminance comme pseudo-carte de profondeur déterministe
            luma = img.mean(axis=0)
            vecs.append(depth_grid_descriptor(luma, box=box, input_size=self.input_size, grid=8))
        return EncodedBatch(global_vectors=np.stack(vecs))


def test_depth_registered_not_kept_and_bench(atlas_env, tmp_path):
    """Depth Anything V2 est enregistré dans NOT_KEPT et mesurable par ``pairs bench`` et ``composition``."""
    assert "depth_anything_v2_small" in ENCODERS
    assert "depth_anything" in NOT_KEPT
    key, label, _ = describe_encoder("depth_anything_v2_small")
    assert key == "profondeur" and "Depth Anything" in label

    src_settings, n = atlas_env
    data_copy = tmp_path / "data"
    shutil.copytree(src_settings.data_dir, data_copy)
    s = get_settings(data_copy)

    fake = _FakeDepth()
    run = extract(fake, s.catalog_path, s.runs_dir, batch_size=6, workers=1)
    assert run.manifest["status"] == "complete" and run.manifest["outputs"]["ok"] == n
    assert len(fake.seen_boxes) == n
    assert not (run.path / "regions.npy").exists()

    # Par défaut, la profondeur n'est pas exposée dans l'Atlas ni le serveur MCP
    data = AtlasData.load(s)
    assert "profondeur" not in data.spaces.runs

    # Ajout de paires annotées pour vérifier `pairs bench` et `composition`
    reds = [i for i, m in data.meta.items() if m.get("artist") == "Rouge"]
    blues = [i for i, m in data.meta.items() if m.get("artist") == "Bleu"]
    add_pair(pairs_path(s), Pair(reds[0], reds[1], "meme_composition", "annotée", "validée", "synthétique"))
    add_pair(pairs_path(s), Pair(blues[0], blues[1], "meme_composition", "annotée", "validée", "synthétique"))

    rc = cli_main(["--data", str(s.data_dir), "pairs", "bench", "--spaces", "couleur,profondeur"])
    assert rc == 0
    assert Spaces.include_not_kept is False

    reports = list((s.data_dir / "bench").glob("pairs_report_*.json"))
    assert len(reports) == 1
    rep = json.loads(reports[0].read_text(encoding="utf-8"))
    assert rep["spaces"] == ["couleur", "profondeur"]
    assert any(r["space"] == "profondeur" and r["type"] == "meme_composition" for r in rep["results"])

    rc_comp = cli_main(["--data", str(s.data_dir), "composition"])
    assert rc_comp is None or rc_comp == 0
    assert Spaces.include_not_kept is False
    comp_reports = list((s.data_dir / "bench").glob("composition_report_*.json"))
    assert len(comp_reports) == 1
    comp = json.loads(comp_reports[0].read_text(encoding="utf-8"))
    assert any(r["space"] == "profondeur" and r["type"] == "meme_composition" for r in comp["results"])


def test_depth_encoder_torch_on_synthetic_corpus(atlas_env, tmp_path):
    """DepthAnythingEncoder avec un module PyTorch local produit des vecteurs 64-D alignés sur l'œuvre."""
    torch = pytest.importorskip("torch")

    class _FakeOut:
        def __init__(self, d):
            self.predicted_depth = d

    class TinyDepth(torch.nn.Module):
        def forward(self, pixel_values: torch.Tensor):
            # Gradient spatial + moyenne des canaux pour produire une carte de profondeur non triviale
            n, _, h, w = pixel_values.shape
            yy = torch.linspace(0.0, 1.0, h, device=pixel_values.device).view(1, h, 1)
            return _FakeOut(pixel_values.mean(dim=1) + 0.5 * yy.expand(n, h, w))

    # input_size=448 (défaut CLI DINOv3) doit retomber sur la résolution native 518 px
    enc = get_encoder("depth_anything_v2_small", model=TinyDepth(), device="cpu", input_size=448)
    assert enc.name == "depth_anything_v2_small" and enc.dim == 64 and enc.input_size == 518
    assert enc.patch_size is None and enc.needs_boxes is True
    desc = enc.describe()
    assert desc["source"] == "huggingface" and desc["grid"] == 8 and desc["descriptor"] == "zscore_grid_artwork"

    # Cohérence numérique entre PyTorch GPU/CPU et la référence NumPy pure
    rng = np.random.default_rng(7)
    sample = rng.standard_normal((2, 3, 518, 518)).astype(np.float32)
    boxes = [(0, 60, 518, 398), (80, 0, 358, 518)]
    out = enc.encode(sample, boxes=boxes).global_vectors
    with torch.inference_mode():
        raw_depth = enc.model(pixel_values=torch.from_numpy(sample)).predicted_depth.numpy()
    for i in range(2):
        ref = depth_grid_descriptor(raw_depth[i], box=boxes[i], input_size=518, grid=8)
        assert np.allclose(out[i], ref, atol=1e-4)

    # Extraction complète sur le corpus synthétique
    src_settings, n = atlas_env
    runs_dir = tmp_path / "runs"
    run = extract(enc, src_settings.catalog_path, runs_dir, batch_size=6, workers=1)
    assert run.manifest["status"] == "complete"
    assert run.manifest["outputs"]["ok"] == n and run.manifest["outputs"]["failed"] == 0
    assert not (run.path / "regions.npy").exists()

    store = FeatureStore.open(run)
    vecs = np.asarray(store.global_vectors, dtype=np.float32)
    assert vecs.shape == (n, 64)
    assert np.allclose(np.linalg.norm(vecs, axis=1), 1.0, atol=1e-2)
