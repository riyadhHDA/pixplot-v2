"""Tests de l'encodeur PE-Core (sujet et recherche par phrase) sur le petit corpus synthétique."""

from __future__ import annotations

import json
import shutil

import numpy as np
import pytest
from PIL import Image

from pixplot.analysis.critique import card as critique_card
from pixplot.analysis.pairbench import Pair, add_pair, pairs_path
from pixplot.api.data import AtlasData
from pixplot.api.search import SearchEngines
from pixplot.api.spaces import NOT_KEPT, Spaces, describe_encoder
from pixplot.cli import main as cli_main
from pixplot.config import get_settings
from pixplot.encoders.base import EncodedBatch, Encoder
from pixplot.encoders.pe_core import _build_text_tower, tokenize_pe_core
from pixplot.encoders.registry import ENCODERS, get_encoder
from pixplot.features.extract import extract
from pixplot.features.store import FeatureStore


class _DummyTokenizer:
    bos_token_id = 100
    eos_token_id = 101

    def encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
        return [1 + (ord(ch) % 90) for ch in text.strip().lower()]


def test_pe_core_tokenize_no_torch():
    """Le découpage texte PE-Core encadre par BOS/EOT, tronque à context_length et complète par 0."""
    tok = _DummyTokenizer()
    arr = tokenize_pe_core(tok, ["abc", "abcdefghijklmno"], context_length=8)
    assert arr.shape == (2, 8) and arr.dtype == np.int64
    assert arr[0, 0] == 100 and arr[0, 4] == 101 and np.all(arr[0, 5:] == 0)
    # Tronqué : 1 BOS + 6 jetons + 1 EOT = 8
    assert arr[1, 0] == 100 and arr[1, 7] == 101
    # argmax retrouve bien l'indice du jeton EOT
    assert arr.argmax(axis=-1).tolist() == [4, 7]


class _FakePECore(Encoder):
    """Encodeur léger sans PyTorch, au nom ``pe_core_l14``, pour tester Spaces, bench et texte."""

    name = "pe_core_l14"
    dim = 6
    input_size = 336
    patch_size = None

    def encode(self, batch: np.ndarray) -> EncodedBatch:
        means = batch.mean(axis=(2, 3))
        stds = batch.std(axis=(2, 3))
        raw = np.concatenate([means, stds], axis=1).astype(np.float32)
        norms = np.maximum(np.linalg.norm(raw, axis=1, keepdims=True), 1e-12)
        return EncodedBatch(global_vectors=raw / norms)

    def encode_text(self, texts: list[str]) -> np.ndarray:
        out = []
        for t in texts:
            v = np.array([1.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32) if "rouge" in t.lower() else np.array(
                [0.0, 0.0, 1.0, 0.0, 0.0, 0.0], dtype=np.float32
            )
            out.append(v / np.linalg.norm(v))
        return np.stack(out)


def test_pe_core_registered_not_kept_and_bench(atlas_env, tmp_path, monkeypatch):
    """PE-Core est enregistré comme regard évalué (NOT_KEPT), mesurable et interrogeable par phrase."""
    assert "pe_core_l14" in ENCODERS and "pe_core_b16" in ENCODERS and "pe_core_g14" in ENCODERS
    assert "pe_core" in NOT_KEPT
    key, label, _ = describe_encoder("pe_core_l14")
    assert key == "sujet_pe" and "PE-Core" in label
    assert "PE-Core" in critique_card("sujet_pe")["model"]

    src_settings, n = atlas_env
    data_copy = tmp_path / "data"
    shutil.copytree(src_settings.data_dir, data_copy)
    s = get_settings(data_copy)

    fake = _FakePECore()
    run = extract(fake, s.catalog_path, s.runs_dir, batch_size=6, workers=1)
    assert run.manifest["status"] == "complete" and run.manifest["outputs"]["ok"] == n
    assert not (run.path / "regions.npy").exists()

    # Par défaut, PE-Core n'est pas proposé dans l'Atlas ni le serveur MCP
    data = AtlasData.load(s)
    assert "sujet_pe" not in data.spaces.runs

    # Recherche par phrase branchée sur PE-Core via encoder="pe_core"
    monkeypatch.setattr("pixplot.api.search.get_encoder", lambda *a, **kw: fake)
    engines = SearchEngines(data)
    res = engines.text("tableau rouge", k=5, encoder="pe_core")
    assert res["features"] == run.id
    assert len(res["results"]) == 5

    # Mesurable via `pixplot pairs bench --spaces couleur,sujet_pe`
    reds = [i for i, m in data.meta.items() if m.get("artist") == "Rouge"]
    blues = [i for i, m in data.meta.items() if m.get("artist") == "Bleu"]
    add_pair(pairs_path(s), Pair(reds[0], reds[1], "meme_sujet", "annotée", "validée", "synthétique"))
    add_pair(pairs_path(s), Pair(blues[0], blues[1], "meme_sujet", "annotée", "validée", "synthétique"))

    rc = cli_main(["--data", str(s.data_dir), "pairs", "bench", "--spaces", "couleur,sujet_pe"])
    assert rc == 0
    assert Spaces.include_not_kept is False

    reports = list((s.data_dir / "bench").glob("pairs_report_*.json"))
    assert len(reports) == 1
    rep = json.loads(reports[0].read_text(encoding="utf-8"))
    assert rep["spaces"] == ["couleur", "sujet_pe"]
    pe_rows = [r for r in rep["results"] if r["space"] == "sujet_pe" and r["type"] == "meme_sujet"]
    assert len(pe_rows) == 1 and pe_rows[0]["n"] == 4 and pe_rows[0]["r10"] == 1.0


def test_pe_core_encoder_torch_and_text_tower(atlas_env, tmp_path):
    """PECoreEncoder avec tour visuelle + tour texte causale produit des vecteurs normalisés."""
    torch = pytest.importorskip("torch")

    class TinyVisual(torch.nn.Module):
        def forward(self, x: torch.Tensor) -> torch.Tensor:
            m = x.mean(dim=(2, 3))
            s = x.std(dim=(2, 3))
            base = torch.cat([m, s], dim=1)
            return base.repeat(1, 3)[:, :16]

    text_tower = _build_text_tower(
        torch, vocab_size=128, context_length=8, width=16, heads=2, layers=1, output_dim=16,
    )
    # Initialisation déterministe des paramètres nn.Parameter (empty par défaut)
    torch.manual_seed(0)
    with torch.no_grad():
        text_tower.positional_embedding.normal_(std=0.02)
        text_tower.text_projection.normal_(std=0.02)

    # input_size=448 (défaut CLI DINOv3) doit retomber sur 336 pour pe_core_l14
    enc = get_encoder(
        "pe_core_l14",
        device="cpu",
        input_size=448,
        vision_model=TinyVisual(),
        text_model=text_tower,
        tokenizer=_DummyTokenizer(),
    )
    enc.dim = 16
    assert enc.name == "pe_core_l14" and enc.input_size == 336 and enc.patch_size is None
    assert enc.describe()["normalize"] == "pe_core (0.5, 0.5)"

    # Prétraitement : letterbox centré, normalisation [-1, 1]
    arr, box = enc.preprocess(Image.new("RGB", (200, 100), (255, 0, 128)))
    assert arr.shape == (3, 336, 336) and box[2] == 336 and box[3] == 168
    assert arr.min() >= -1.01 and arr.max() <= 1.01

    tvecs = enc.encode_text(["Annonciation", "nature morte au crâne"])
    assert tvecs.shape == (2, 16)
    assert np.allclose(np.linalg.norm(tvecs, axis=1), 1.0, atol=1e-5)

    src_settings, n = atlas_env
    runs_dir = tmp_path / "runs"
    run = extract(enc, src_settings.catalog_path, runs_dir, batch_size=6, workers=1)
    assert run.manifest["status"] == "complete" and run.manifest["outputs"]["ok"] == n
    store = FeatureStore.open(run)
    vecs = np.asarray(store.global_vectors, dtype=np.float32)
    assert vecs.shape == (n, 16)
    assert np.allclose(np.linalg.norm(vecs, axis=1), 1.0, atol=1e-2)
