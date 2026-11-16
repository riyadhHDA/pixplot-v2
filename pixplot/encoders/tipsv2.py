"""Encodeur TIPSv2 (Google DeepMind, CVPR 2026, Apache 2.0) : texte, image ET zones dans le
même espace.

C'est ce qui manquait : SigLIP 2 compare une phrase à une image entière, DINOv3 compare des
zones entre elles ; TIPSv2 aligne chaque **zone de 14 × 14 pixels** avec le texte (iBOT++ et
distillation des zones, voir l'article). On peut donc chercher « une auréole » ou « une main
qui bénit » et savoir *où* elle se trouve dans le tableau.

Prétraitement : l'œuvre entière dans un carré (letterbox, fond gris), pixels dans [0, 1]
sans normalisation ImageNet (consigne du modèle). Tailles fixes, car le GPU AMD recompile
~20 s pour chaque nouvelle taille d'entrée.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from .base import EncodedBatch, Encoder, letterbox, letterbox_box

MODELS = {"tipsv2_b14": ("google/tipsv2-b14", 768), "tipsv2_l14": ("google/tipsv2-l14", 1024),
          "tipsv2_so400m14": ("google/tipsv2-so400m14", 1152)}
PATCH = 14
SKIP_TOKENS = 2          # CLS + 1 registre, puis les zones


class TIPSv2Encoder(Encoder):
    patch_size = PATCH

    def __init__(self, arch: str = "tipsv2_b14", hf_model: str | None = None, input_size: int = 448,
                 device: str | None = None, fp16: bool = True):
        import torch
        from transformers.models.tipsv2 import Tipsv2Model, Tipsv2Processor

        if arch not in MODELS:
            raise ValueError(f"Architecture inconnue : {arch} (choix : {', '.join(MODELS)})")
        if input_size % PATCH:
            raise ValueError(f"La taille d'entrée doit être un multiple de {PATCH}")
        default_id, dim = MODELS[arch]
        self.name, self.dim, self.input_size = arch, dim, input_size
        self.weights = hf_model or default_id
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.fp16 = fp16 and self.device != "cpu"
        self._torch = torch
        self.model = Tipsv2Model.from_pretrained(self.weights).eval().to(self.device)
        self.processor = Tipsv2Processor.from_pretrained(self.weights)

    # ------------------------------------------------------------------ images
    def preprocess(self, image: Image.Image, size: int | None = None):
        size = size or self.input_size
        box = letterbox_box(*image.size, size)
        canvas = letterbox(image.convert("RGB"), size, fill=(128, 128, 128))
        return (np.asarray(canvas, dtype=np.float32) / 255.0).transpose(2, 0, 1), box

    def _autocast(self):
        return self._torch.autocast(device_type="cuda" if self.device != "cpu" else "cpu",
                                    dtype=self._torch.float16, enabled=self.fp16)

    def _forward(self, batch: np.ndarray):
        torch = self._torch
        x = torch.from_numpy(np.ascontiguousarray(batch)).to(self.device)
        with torch.inference_mode(), self._autocast():
            out = self.model.get_image_features(pixel_values=x)
        return out.pooler_output.float(), out.last_hidden_state[:, SKIP_TOKENS:].float()

    def encode(self, batch: np.ndarray) -> EncodedBatch:
        torch = self._torch
        g, _ = self._forward(batch)
        return EncodedBatch(global_vectors=torch.nn.functional.normalize(g, dim=-1).cpu().numpy())

    def dense(self, batch: np.ndarray) -> np.ndarray:
        """Vecteurs de zones normalisés, (B, H/14, W/14, D), alignés avec le texte."""
        torch = self._torch
        _, p = self._forward(batch)
        side = batch.shape[-1] // PATCH
        p = torch.nn.functional.normalize(p, dim=-1)
        return p.reshape(p.shape[0], batch.shape[-2] // PATCH, side, -1).cpu().numpy()

    # ------------------------------------------------------------------ texte
    def encode_text(self, texts: list[str]) -> np.ndarray:
        torch = self._torch
        inputs = self.processor(text=[t.lower() for t in texts], padding=True, truncation=True,
                                max_length=64, return_tensors="pt").to(self.device)
        with torch.inference_mode(), self._autocast():
            feats = self.model.get_text_features(**inputs).pooler_output
        return torch.nn.functional.normalize(feats.float(), dim=-1).cpu().numpy()

    def describe(self) -> dict:
        return {**super().describe(), "source": "huggingface", "weights": self.weights,
                "device": self.device, "fp16": self.fp16, "normalize": "[0, 1], sans ImageNet"}
