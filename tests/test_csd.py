"""Tests de l'encodeur CSD (Contrastive Style Descriptors) sur le petit corpus synthétique."""

from __future__ import annotations

import json
import shutil

import numpy as np
import pytest
from PIL import Image

from pixplot.analysis.critique import card as critique_card
from pixplot.analysis.pairbench import Pair, add_pair, pairs_path
from pixplot.api.data import AtlasData
from pixplot.api.spaces import NOT_KEPT, Spaces, describe_encoder
from pixplot.cli import main as cli_main
from pixplot.config import get_settings
from pixplot.encoders.base import EncodedBatch, Encoder
from pixplot.encoders.csd import CLIP_PAD_RGB, build_csd_model, preprocess_csd
from pixplot.encoders.registry import ENCODERS, get_encoder
from pixplot.features.extract import extract
from pixplot.features.store import FeatureStore


def test_csd_preprocess_no_torch():
    """Le prétraitement CSD conserve l'œuvre entière (letterbox) avec la normalisation CLIP."""
    img = Image.new("RGB", (400, 200), CLIP_PAD_RGB)
    arr, box = preprocess_csd(img, size=224)
    assert arr.shape == (3, 224, 224) and arr.dtype == np.float32
    assert box == (0, 56, 224, 112)
    # Une image remplie de la moyenne CLIP vaut ≈ 0 partout après normalisation
    assert np.abs(arr).max() < 0.05


class _FakeCSD(Encoder):
    """Encodeur léger sans PyTorch, au nom ``csd_vitl14``, pour tester Spaces et pairs bench."""

    name = "csd_vitl14"
    dim = 6
    input_size = 224
    patch_size = None

    def encode(self, batch: np.ndarray) -> EncodedBatch:
        means = batch.mean(axis=(2, 3))
        stds = batch.std(axis=(2, 3))
        raw = np.concatenate([means, stds], axis=1).astype(np.float32)
        norms = np.maximum(np.linalg.norm(raw, axis=1, keepdims=True), 1e-12)
        return EncodedBatch(global_vectors=raw / norms)


def test_csd_registered_not_kept_and_bench(atlas_env, tmp_path):
    """CSD est enregistré comme regard évalué (NOT_KEPT) et mesurable par ``pixplot pairs bench``."""
    assert "csd_vitl14" in ENCODERS
    assert "csd" in NOT_KEPT
    key, label, _ = describe_encoder("csd_vitl14")
    assert key == "touche_csd" and "CSD" in label
    assert "CSD" in critique_card("touche_csd")["model"]

    src_settings, n = atlas_env
    data_copy = tmp_path / "data"
    shutil.copytree(src_settings.data_dir, data_copy)
    s = get_settings(data_copy)

    run = extract(_FakeCSD(), s.catalog_path, s.runs_dir, batch_size=6, workers=1)
    assert run.manifest["status"] == "complete" and run.manifest["outputs"]["ok"] == n
    assert not (run.path / "regions.npy").exists()

    # Par défaut, CSD n'est pas proposé dans l'Atlas ni le serveur MCP
    data = AtlasData.load(s)
    assert "touche_csd" not in data.spaces.runs

    # Mesurable explicitement via `pixplot pairs bench --spaces couleur,touche_csd`
    reds = [i for i, m in data.meta.items() if m.get("artist") == "Rouge"]
    blues = [i for i, m in data.meta.items() if m.get("artist") == "Bleu"]
    add_pair(pairs_path(s), Pair(reds[0], reds[1], "meme_facture", "annotée", "validée", "synthétique"))
    add_pair(pairs_path(s), Pair(blues[0], blues[1], "meme_facture", "annotée", "validée", "synthétique"))

    rc = cli_main(["--data", str(s.data_dir), "pairs", "bench", "--spaces", "couleur,touche_csd"])
    assert rc == 0
    assert Spaces.include_not_kept is False

    reports = list((s.data_dir / "bench").glob("pairs_report_*.json"))
    assert len(reports) == 1
    rep = json.loads(reports[0].read_text(encoding="utf-8"))
    assert rep["spaces"] == ["couleur", "touche_csd"]
    csd_rows = [r for r in rep["results"] if r["space"] == "touche_csd" and r["type"] == "meme_facture"]
    assert len(csd_rows) == 1 and csd_rows[0]["n"] == 4 and csd_rows[0]["r10"] == 1.0


def test_csd_encoder_torch_on_synthetic_corpus(atlas_env, tmp_path):
    """CSDEncoder avec architecture ViT locale extrait des vecteurs de style normalisés."""
    torch = pytest.importorskip("torch")

    torch.manual_seed(0)
    tiny = build_csd_model(
        torch, input_resolution=224, patch_size=56, width=16, layers=1, heads=2, output_dim=12,
    )
    with torch.no_grad():
        tiny.backbone.class_embedding.normal_(std=0.02)
        tiny.backbone.positional_embedding.normal_(std=0.02)
        tiny.last_layer_style.normal_(std=0.02)

    # input_size=448 (défaut CLI DINOv3) doit retomber sur la résolution native 224 px
    enc = get_encoder("csd_vitl14", model=tiny, device="cpu", input_size=448)
    enc.dim = 12
    assert enc.name == "csd_vitl14" and enc.input_size == 224 and enc.patch_size is None
    desc = enc.describe()
    assert desc["normalize"] == "clip" and desc["eval_embed"] == "style_head"

    src_settings, n = atlas_env
    runs_dir = tmp_path / "runs"
    run = extract(enc, src_settings.catalog_path, runs_dir, batch_size=6, workers=1)
    assert run.manifest["status"] == "complete"
    assert run.manifest["outputs"]["ok"] == n and run.manifest["outputs"]["failed"] == 0
    assert not (run.path / "regions.npy").exists()

    store = FeatureStore.open(run)
    vecs = np.asarray(store.global_vectors, dtype=np.float32)
    assert vecs.shape == (n, 12)
    assert np.allclose(np.linalg.norm(vecs, axis=1), 1.0, atol=1e-2)
