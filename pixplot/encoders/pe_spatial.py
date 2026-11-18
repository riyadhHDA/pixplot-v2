"""Encodeur PE-Spatial (Meta, Perception Encoder, 2025) — candidat pour le regard « composition ».

PE-Spatial est la version du Perception Encoder affinée pour des vecteurs **par zone** de bonne
qualité (« ce qui est représenté, et où »). Poids sous licence Apache 2.0, chargés par ``timm``
depuis Hugging Face (``timm/vit_pe_spatial_base_patch16_512.fb``) au premier usage.

Vecteur global : moyenne des vecteurs de patchs (le token de classe de PE-Spatial n'est pas
entraîné pour résumer l'image). Grille de patchs : 32 × 32 à 512 px, mise en commun par zones
(1 × 1, 2 × 2, 4 × 4) par l'extraction, comme pour DINOv3. La disposition « 4 × 4 » sert au
banc d'essai de composition (``pixplot.analysis.composition``).
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from .base import EncodedBatch, Encoder, letterbox, letterbox_box

MODELS = {"pe_spatial_b16": ("vit_pe_spatial_base_patch16_512.fb", 768, 16, 512)}


class PESpatialEncoder(Encoder):
    def __init__(self, arch: str = "pe_spatial_b16", input_size: int | None = None,
                 device: str | None = None, fp16: bool = True, **_):
        import timm
        import torch

        if arch not in MODELS:
            raise ValueError(f"Architecture inconnue : {arch} (choix : {', '.join(MODELS)})")
        hub, dim, patch, size = MODELS[arch]
        self.name, self.dim, self.patch_size = arch, dim, patch
        self.input_size = input_size or size
        if self.input_size % patch:
            raise ValueError(f"input_size doit être un multiple de {patch}")
        self.weights = f"timm/{hub}"
        self._torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.fp16 = fp16 and self.device != "cpu"
        self.model = timm.create_model(hub.split(".")[0], pretrained=True,
                                       img_size=self.input_size).eval().to(self.device)
        cfg = timm.data.resolve_model_data_config(self.model)
        self.mean = np.array(cfg["mean"], dtype=np.float32)
        self.std = np.array(cfg["std"], dtype=np.float32)
        self.prefix = int(getattr(self.model, "num_prefix_tokens", 1))
        if self.device != "cpu":
            torch.cuda.reset_peak_memory_stats()

    def preprocess(self, image: Image.Image):
        # bandes de la couleur moyenne du modèle (≈ 0 après normalisation), sans recadrer
        fill = tuple(int(round(m * 255)) for m in self.mean)
        box = letterbox_box(*image.size, self.input_size)
        arr = np.asarray(letterbox(image, self.input_size, fill), dtype=np.float32) / 255.0
        return ((arr - self.mean) / self.std).transpose(2, 0, 1), box

    def encode(self, batch: np.ndarray) -> EncodedBatch:
        torch = self._torch
        x = torch.from_numpy(batch).to(self.device, non_blocking=True)
        with torch.inference_mode(), torch.autocast(device_type="cuda" if self.device != "cpu" else "cpu",
                                                    dtype=torch.float16, enabled=self.fp16):
            tokens = self.model.forward_features(x)
        g = self.input_size // self.patch_size
        patches = tokens[:, self.prefix:].float()
        glob = torch.nn.functional.normalize(patches.mean(dim=1), dim=-1)
        return EncodedBatch(global_vectors=glob.cpu().numpy(),
                            patch_grid=patches.reshape(len(batch), g, g, -1).cpu().numpy())

    def runtime_stats(self) -> dict:
        if self.device == "cpu":
            return {"device": "cpu"}
        torch = self._torch
        return {"device": torch.cuda.get_device_name(0),
                "vram_peak_mib": round(torch.cuda.max_memory_allocated() / 2**20)}

    def describe(self) -> dict:
        return {**super().describe(), "source": "timm", "weights": self.weights,
                "device": self.device, "fp16": self.fp16}
