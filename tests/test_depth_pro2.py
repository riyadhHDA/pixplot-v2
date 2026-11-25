"""Tests de l'encodeur Depth Pro 2 sur le petit corpus synthétique."""

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


class _FakeDepthPro2(Encoder):
    """Encodeur léger sans PyTorch, au nom ``depth_pro2_base``, vérifiant le passage des boîtes."""

    name = "depth_pro2_base"
    dim = 64
    input_size = 128
    patch_size = None
    needs_boxes = True

    def __init__(self):
        self.seen_boxes: list[tuple[int, int, int, int]] = []

    def encode(self, batch: np.ndarray, boxes=None) -> EncodedBatch:
        assert boxes is not None and len(boxes) == len(batch)
        self.seen_boxes.extend(boxes)
        vecs = []
        for img, box in zip(batch, boxes):
            luma = img.mean(axis=0)
            vecs.append(depth_grid_descriptor(luma, box=box, input_size=self.input_size, grid=8))
        return EncodedBatch(global_vectors=np.stack(vecs))


def test_depth_pro2_registered_not_kept_and_bench(atlas_env, tmp_path):
    """Depth Pro 2 est enregistré dans NOT_KEPT et mesurable par ``pairs bench`` et ``composition``."""
    for arch in ("depth_pro2_small", "depth_pro2_base", "depth_pro2_large"):
        assert arch in ENCODERS
    assert "depth_pro2" in NOT_KEPT
    key, label, _ = describe_encoder("depth_pro2_base")
    assert key == "profondeur_dp2" and "Depth Pro 2" in label

    src_settings, n = atlas_env
    data_copy = tmp_path / "data"
    shutil.copytree(src_settings.data_dir, data_copy)
    s = get_settings(data_copy)

    fake = _FakeDepthPro2()
    run = extract(fake, s.catalog_path, s.runs_dir, batch_size=6, workers=1)
    assert run.manifest["status"] == "complete" and run.manifest["outputs"]["ok"] == n
    assert len(fake.seen_boxes) == n
    assert not (run.path / "regions.npy").exists()

    # Par défaut, profondeur_dp2 n'est pas exposée dans l'Atlas ni le serveur MCP
    data = AtlasData.load(s)
    assert "profondeur_dp2" not in data.spaces.runs

    # Ajout de paires annotées pour vérifier `pairs bench` et `composition`
    reds = [i for i, m in data.meta.items() if m.get("artist") == "Rouge"]
    blues = [i for i, m in data.meta.items() if m.get("artist") == "Bleu"]
    add_pair(pairs_path(s), Pair(reds[0], reds[1], "meme_composition", "annotée", "validée", "synthétique"))
    add_pair(pairs_path(s), Pair(blues[0], blues[1], "meme_composition", "annotée", "validée", "synthétique"))

    rc = cli_main(["--data", str(s.data_dir), "pairs", "bench", "--spaces", "couleur,profondeur_dp2"])
    assert rc == 0
    assert Spaces.include_not_kept is False

    reports = list((s.data_dir / "bench").glob("pairs_report_*.json"))
    assert len(reports) == 1
    rep = json.loads(reports[0].read_text(encoding="utf-8"))
    assert rep["spaces"] == ["couleur", "profondeur_dp2"]
    assert any(r["space"] == "profondeur_dp2" and r["type"] == "meme_composition" for r in rep["results"])

    rc_comp = cli_main(["--data", str(s.data_dir), "composition"])
    assert rc_comp is None or rc_comp == 0
    assert Spaces.include_not_kept is False
    comp_reports = list((s.data_dir / "bench").glob("composition_report_*.json"))
    assert len(comp_reports) == 1
    comp = json.loads(comp_reports[0].read_text(encoding="utf-8"))
    assert any(r["space"] == "profondeur_dp2" and r["type"] == "meme_composition" for r in comp["results"])


def test_depth_pro2_encoder_torch_on_synthetic_corpus(atlas_env, tmp_path):
    """DepthPro2Encoder avec un module PyTorch local produit des vecteurs 64-D alignés sur l'œuvre."""
    torch = pytest.importorskip("torch")

    class TinyDepthPro2(torch.nn.Module):
        def forward(self, x: torch.Tensor, autocast_dtype=None):
            n, _, h, w = x.shape
            yy = torch.linspace(0.0, 1.0, h, device=x.device).view(1, h, 1)
            return x.mean(dim=1) + 0.5 * yy.expand(n, h, w)

    # input_size=448 (défaut CLI DINOv3) doit retomber sur la résolution native 512 px
    enc = get_encoder("depth_pro2_base", model=TinyDepthPro2(), device="cpu", input_size=448)
    assert enc.name == "depth_pro2_base" and enc.dim == 64 and enc.input_size == 512
    assert enc.patch_size is None and enc.needs_boxes is True
    desc = enc.describe()
    assert desc["source"] == "huggingface" and desc["grid"] == 8 and desc["descriptor"] == "zscore_grid_artwork"

    # Vérifie que input_size non multiple de 32 est refusé
    with pytest.raises(ValueError, match="multiple de 32"):
        get_encoder("depth_pro2_base", model=TinyDepthPro2(), device="cpu", input_size=500)

    # Cohérence numérique entre PyTorch et la référence NumPy pure
    rng = np.random.default_rng(11)
    sample = rng.standard_normal((2, 3, 512, 512)).astype(np.float32)
    boxes = [(0, 64, 512, 384), (64, 0, 384, 512)]
    out = enc.encode(sample, boxes=boxes).global_vectors
    with torch.inference_mode():
        raw_depth = enc.model(torch.from_numpy(sample)).numpy()
    for i in range(2):
        ref = depth_grid_descriptor(raw_depth[i], box=boxes[i], input_size=512, grid=8)
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
