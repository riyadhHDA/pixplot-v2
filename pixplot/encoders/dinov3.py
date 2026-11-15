"""Encodeur DINOv3 (Meta). Non testé sur GPU pour l'instant (étape 1).

Prérequis :
- PyTorch ROCm installé (roues AMD), ``torch.cuda.is_available()`` doit valoir True ;
- dépôt cloné dans ``vendor/dinov3`` ;
- poids téléchargés après acceptation de la licence Meta, ex. ``weights/dinov3_vitb16.pth``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import numpy as np
from PIL import Image

from .base import EncodedBatch, Encoder, letterbox, to_normalized_array

ARCH_DIMS = {"dinov3_vitb16": 768, "dinov3_vitl16": 1024}


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
            raise ValueError(f"Architecture inconnue : {arch}")
        if input_size % self.patch_size:
            raise ValueError("input_size doit être un multiple de 16")

        self.name = arch
        self.dim = ARCH_DIMS[arch]
        self.input_size = input_size
        self.weights = Path(weights)
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.fp16 = fp16 and self.device != "cpu"

        self._torch = torch
        self.model = torch.hub.load(str(repo), arch, source="local", weights=str(self.weights))
        self.model.eval().to(self.device)

    def encode(self, images: Sequence[Image.Image]) -> EncodedBatch:
        torch = self._torch
        batch = np.stack([to_normalized_array(letterbox(im, self.input_size)) for im in images])
        x = torch.from_numpy(batch).to(self.device)

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

        return EncodedBatch(
            global_vectors=cls.cpu().numpy(),
            patch_grid=patches.cpu().numpy(),
        )

    def describe(self) -> dict:
        return {**super().describe(), "weights": self.weights.name, "device": self.device, "fp16": self.fp16}
