"""Tests de l'encodeur SSCD (détection de copies) sur le petit corpus synthétique."""

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
from pixplot.encoders.registry import ENCODERS, get_encoder
from pixplot.features.extract import extract
from pixplot.features.store import FeatureStore


class _FakeSSCD(Encoder):
    """Encodeur léger sans PyTorch, au nom ``sscd_disc_large``, pour tester Spaces et pairs bench."""

    name = "sscd_disc_large"
    dim = 16
    input_size = 320
    patch_size = None

    def encode(self, batch: np.ndarray) -> EncodedBatch:
        # Moyenne et écart-type par canal RGB, répétés et normalisés L2
        means = batch.mean(axis=(2, 3))
        stds = batch.std(axis=(2, 3))
        raw = np.concatenate([means, stds, means * 0.5, stds * 0.5, means, stds[:, :1]], axis=1).astype(np.float32)
        norms = np.maximum(np.linalg.norm(raw, axis=1, keepdims=True), 1e-12)
        return EncodedBatch(global_vectors=raw / norms)


def test_sscd_registered_not_kept_and_bench(atlas_env, tmp_path):
    """SSCD est enregistré comme regard évalué (NOT_KEPT) et mesurable par ``pixplot pairs bench``."""
    assert "sscd_disc_mixup" in ENCODERS and "sscd_disc_large" in ENCODERS
    assert "sscd" in NOT_KEPT
    key, label, _ = describe_encoder("sscd_disc_large")
    assert key == "copie" and "SSCD" in label

    src_settings, n = atlas_env
    data_copy = tmp_path / "data"
    shutil.copytree(src_settings.data_dir, data_copy)
    s = get_settings(data_copy)

    run = extract(_FakeSSCD(), s.catalog_path, s.runs_dir, batch_size=6, workers=1)
    assert run.manifest["status"] == "complete" and run.manifest["outputs"]["ok"] == n
    assert not (run.path / "regions.npy").exists()

    # Par défaut, SSCD n'est pas proposé dans l'Atlas ni le serveur MCP
    data = AtlasData.load(s)
    assert "copie" not in data.spaces.runs

    # Mais il est mesurable explicitement via `pixplot pairs bench --spaces couleur,copie`
    reds = [i for i, m in data.meta.items() if m.get("artist") == "Rouge"]
    blues = [i for i, m in data.meta.items() if m.get("artist") == "Bleu"]
    add_pair(pairs_path(s), Pair(reds[0], reds[1], "filiation", "annotée", "validée", "synthétique"))
    add_pair(pairs_path(s), Pair(blues[0], blues[1], "filiation", "annotée", "validée", "synthétique"))

    rc = cli_main(["--data", str(s.data_dir), "pairs", "bench", "--spaces", "couleur,copie"])
    assert rc == 0
    assert Spaces.include_not_kept is False  # restauré après le banc

    reports = list((s.data_dir / "bench").glob("pairs_report_*.json"))
    assert len(reports) == 1
    rep = json.loads(reports[0].read_text(encoding="utf-8"))
    assert rep["spaces"] == ["couleur", "copie"]
    copie_fil = [r for r in rep["results"] if r["space"] == "copie" and r["type"] == "filiation"]
    assert len(copie_fil) == 1 and copie_fil[0]["n"] == 4 and copie_fil[0]["r10"] == 1.0


def test_sscd_encoder_torchscript_on_synthetic_corpus(atlas_env, tmp_path):
    """SSCDEncoder charge un modèle TorchScript local et extrait des vecteurs normalisés."""
    torch = pytest.importorskip("torch")

    class TinySSCD(torch.nn.Module):
        def forward(self, x: torch.Tensor) -> torch.Tensor:
            # Empreinte 1024-D déterministe à partir des moyennes/écarts-types par canal
            m = x.mean(dim=(2, 3))
            s = x.std(dim=(2, 3))
            base = torch.cat([m, s], dim=1)  # (N, 6)
            reps = base.repeat(1, 171)[:, :1024]
            return torch.nn.functional.normalize(reps, dim=-1)

    pt_path = tmp_path / "sscd_disc_large.torchscript.pt"
    torch.jit.script(TinySSCD().eval()).save(str(pt_path))

    # input_size=448 (défaut CLI DINOv3) doit retomber sur la taille par défaut de SSCD (320)
    enc = get_encoder("sscd_disc_large", weights=pt_path, device="cpu", input_size=448)
    assert enc.name == "sscd_disc_large" and enc.dim == 1024 and enc.input_size == 320 and enc.patch_size is None
    desc = enc.describe()
    assert desc["source"] == "meta-sscd" and desc["weights"] == pt_path.name and desc["fp16"] is False

    src_settings, n = atlas_env
    runs_dir = tmp_path / "runs"
    run = extract(enc, src_settings.catalog_path, runs_dir, batch_size=6, workers=1)
    assert run.manifest["status"] == "complete"
    assert run.manifest["outputs"]["ok"] == n and run.manifest["outputs"]["failed"] == 0
    assert not (run.path / "regions.npy").exists()

    store = FeatureStore.open(run)
    vecs = np.asarray(store.global_vectors, dtype=np.float32)
    assert vecs.shape == (n, 1024)
    assert np.allclose(np.linalg.norm(vecs, axis=1), 1.0, atol=1e-2)

    data = AtlasData.load(src_settings)
    reds = [i for i, m in data.meta.items() if m.get("artist") == "Rouge"]
    top_id, top_score = store.similar(reds[0], k=3)[0]
    assert top_id in reds and top_score > 0.9
