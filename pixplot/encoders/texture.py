"""Encodeur « touche » : la texture de la surface peinte, indépendamment du sujet.

Statistiques (moyenne et écart-type par canal) des patchs d'une couche **intermédiaire**
de DINOv3, à la manière des descripteurs de style (Gatys, Huang & Belongie). Les couches
basses voient le grain, le trait, la touche ; la dernière couche voit plutôt les objets
et la composition. Les bandes du letterbox sont exclues des statistiques.

Mesuré sur 6 424 œuvres WikiArt équilibrées par style (P@10, même style parmi les 10
plus proches) — couche 6 de ViT-B/16 à 448 px contre le token CLS final :
Pointillisme 76 % (47 %), Fauvisme 45 % (32 %), Impressionnisme 38 % (27 %) ; moyenne
tous styles 37 % (41 %). Espace complémentaire, pas un remplaçant.
"""

from __future__ import annotations

import numpy as np

from .base import EncodedBatch
from .dinov3 import ARCH_DIMS, DINOv3Encoder

PAD_EPS = 0.03  # après normalisation, les bandes letterbox valent ~0 sur les trois canaux


class DINOv3TextureEncoder(DINOv3Encoder):
    center_after = True  # vecteurs centrés sur la moyenne du corpus en fin d'extraction

    def __init__(self, arch: str = "dinov3_vitb16_texture", layer: int = 6, **kwargs):
        base = arch.replace("_texture", "")
        kwargs.pop("weights", None)
        kwargs.pop("repo", None)
        super().__init__(arch=base, **kwargs)
        self.name = f"{base}_texture"
        self.layer = layer
        self.dim = 2 * ARCH_DIMS[base]
        self.model_patch_size = self.patch_size
        self.patch_size = None  # pas de vecteurs par zone pour cet espace

    def encode(self, batch: np.ndarray) -> EncodedBatch:
        torch = self._torch
        ps = self.model_patch_size
        g = self.input_size // ps
        n = len(batch)
        pad = np.abs(batch).reshape(n, 3, g, ps, g, ps).max(axis=(1, 3, 5)) < PAD_EPS  # (n, g, g)
        x = torch.from_numpy(batch).to(self.device, non_blocking=True)
        with torch.inference_mode(), torch.autocast(device_type="cuda" if self.device != "cpu" else "cpu",
                                                    dtype=torch.float16, enabled=self.fp16):
            hidden = self.model(pixel_values=x, output_hidden_states=True).hidden_states[self.layer]
        p = hidden[:, 1 + self.n_registers:].float()                       # (n, g*g, D)
        keep = torch.from_numpy(~pad.reshape(n, -1)).to(p.device).float().unsqueeze(-1)
        nk = keep.sum(1).clamp(min=1)
        mu = (p * keep).sum(1) / nk
        sd = (((p - mu[:, None]) ** 2 * keep).sum(1) / nk).sqrt()
        v = torch.nn.functional.normalize(torch.cat([mu, sd], 1), dim=-1)
        return EncodedBatch(global_vectors=v.cpu().numpy(), patch_grid=None)

    def describe(self) -> dict:
        return {**super().describe(), "layer": self.layer, "statistics": "moyenne + écart-type des patchs",
                "patch_size": None, "model_patch_size": self.model_patch_size}
