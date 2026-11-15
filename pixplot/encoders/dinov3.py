"""Encodeur DINOv3 (Meta).

Prérequis :
- PyTorch ROCm installé (roues AMD), ``torch.cuda.is_available()`` doit valoir True ;
- dépôt cloné dans ``vendor/dinov3`` ;
- poids téléchargés après acceptation de la licence Meta, ex. ``weights/dinov3_vitb16.pth``.

Voir docs/INSTALL_GPU.md. Pas encore exécuté sur la 7900 GRE.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .base import EncodedBatch, Encoder

ARCH_DIMS = {"dinov3_vits16": 384, "dinov3_vitb16": 768, "dinov3_vitl16": 1024}


class DINOv3Encoder(Encoder):
    patch_size = 16

    def __init__(
        self,
        weights: str | Path,
        arch: str = "dinov3_vitb16",
        repo: str | Path = "vendor/dinov3",
        input_size: int = 448,
        device: str | None = None,
        fp16: bool = True,
    ):
        import torch  # import tardif : le reste de pixplot fonctionne sans torch

        if arch not in ARCH_DIMS:
            raise ValueError(f"Architecture inconnue : {arch} (choix : {', '.join(ARCH_DIMS)})")
        if input_size % self.patch_size:
            raise ValueError("input_size doit être un multiple de 16")
        weights, repo = Path(weights), Path(repo)
        if not weights.exists():
            raise FileNotFoundError(f"Poids introuvables : {weights} (voir docs/INSTALL_GPU.md)")
        if not (repo / "hubconf.py").exists():
            raise FileNotFoundError(f"Dépôt DINOv3 introuvable : {repo} (voir docs/INSTALL_GPU.md)")

        self.name = arch
        self.dim = ARCH_DIMS[arch]
        self.input_size = input_size
        self.weights = weights
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.fp16 = fp16 and self.device != "cpu"

        self._torch = torch
        self.model = torch.hub.load(str(repo), arch, source="local", weights=str(weights))
        self.model.eval().to(self.device)
        if self.device != "cpu":
            torch.cuda.reset_peak_memory_stats()

    def encode(self, batch: np.ndarray) -> EncodedBatch:
        torch = self._torch
        x = torch.from_numpy(batch).to(self.device, non_blocking=True)

        with torch.inference_mode(), torch.autocast(
            device_type="cuda" if self.device != "cpu" else "cpu",
            dtype=torch.float16,
            enabled=self.fp16,
        ):
            feats = self.model.forward_features(x)

        cls = torch.nn.functional.normalize(feats["x_norm_clstoken"].float(), dim=-1)
        patches = feats["x_norm_patchtokens"].float()  # (N, gh*gw, D), sans tokens registres
        g = self.input_size // self.patch_size
        patches = patches.reshape(patches.shape[0], g, g, -1)
        return EncodedBatch(global_vectors=cls.cpu().numpy(), patch_grid=patches.cpu().numpy())

    def runtime_stats(self) -> dict:
        if self.device == "cpu":
            return {"device": "cpu"}
        torch = self._torch
        return {
            "device": torch.cuda.get_device_name(0),
            "vram_peak_mib": round(torch.cuda.max_memory_allocated() / 2**20),
        }

    def describe(self) -> dict:
        return {**super().describe(), "weights": self.weights.name, "device": self.device, "fp16": self.fp16}
