"""Encodeur SigLIP 2 (Google, Apache 2.0) : images ET textes dans le même espace.

Sert à la recherche en texte libre (« Annonciation avec un jardin »). Le modèle est
multilingue : on peut chercher en français. Accès libre sur Hugging Face, sans demande.

Comme pour DINOv3, l'œuvre entière est conservée (letterbox), mais avec la normalisation
propre à SigLIP (moyenne et écart-type 0,5) et un fond gris neutre.
Pas de vecteurs régionaux : la recherche par détail passe par DINOv3.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from .base import EncodedBatch, Encoder, letterbox, letterbox_box

MODELS = {
    "siglip2_so400m": ("google/siglip2-so400m-patch16-384", 1152, 384),
    "siglip2_base": ("google/siglip2-base-patch16-256", 768, 256),
}
TEXT_LENGTH = 64  # SigLIP a été entraîné avec des textes complétés à 64 jetons


def _tensor(out):
    """Selon la version de transformers, get_*_features renvoie un tenseur ou un objet."""
    return getattr(out, "pooler_output", out)


class SigLIP2Encoder(Encoder):
    patch_size = None  # pas de vecteurs régionaux

    def __init__(self, arch: str = "siglip2_so400m", hf_model: str | None = None,
                 input_size: int | None = None, device: str | None = None, fp16: bool = True):
        import torch
        from transformers import AutoModel, AutoProcessor

        if arch not in MODELS:
            raise ValueError(f"Architecture inconnue : {arch} (choix : {', '.join(MODELS)})")
        default_id, dim, size = MODELS[arch]
        self.name, self.dim = arch, dim
        self.input_size = input_size or size
        self.weights = hf_model or default_id
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.fp16 = fp16 and self.device != "cpu"
        self._torch = torch
        self.model = AutoModel.from_pretrained(self.weights).eval().to(self.device)
        self.processor = AutoProcessor.from_pretrained(self.weights)
        if self.device != "cpu":
            torch.cuda.reset_peak_memory_stats()

    def preprocess(self, image: Image.Image):
        box = letterbox_box(*image.size, self.input_size)
        canvas = letterbox(image, self.input_size, fill=(128, 128, 128))
        arr = (np.asarray(canvas, dtype=np.float32) / 255.0 - 0.5) / 0.5
        return arr.transpose(2, 0, 1), box

    def _autocast(self):
        return self._torch.autocast(device_type="cuda" if self.device != "cpu" else "cpu",
                                    dtype=self._torch.float16, enabled=self.fp16)

    def encode(self, batch: np.ndarray) -> EncodedBatch:
        torch = self._torch
        x = torch.from_numpy(batch).to(self.device)
        with torch.inference_mode(), self._autocast():
            feats = _tensor(self.model.get_image_features(pixel_values=x))
        feats = torch.nn.functional.normalize(feats.float(), dim=-1)
        return EncodedBatch(global_vectors=feats.cpu().numpy())

    def encode_text(self, texts: list[str]) -> np.ndarray:
        """Textes → vecteurs normalisés (N, D), comparables aux vecteurs d'images."""
        torch = self._torch
        inputs = self.processor(text=[t.lower() for t in texts], padding="max_length",
                                max_length=TEXT_LENGTH, truncation=True, return_tensors="pt").to(self.device)
        with torch.inference_mode(), self._autocast():
            feats = _tensor(self.model.get_text_features(**inputs))
        return torch.nn.functional.normalize(feats.float(), dim=-1).cpu().numpy()

    def runtime_stats(self) -> dict:
        if self.device == "cpu":
            return {"device": "cpu"}
        torch = self._torch
        return {"device": torch.cuda.get_device_name(0),
                "vram_peak_mib": round(torch.cuda.max_memory_allocated() / 2**20)}

    def describe(self) -> dict:
        return {**super().describe(), "source": "huggingface", "weights": self.weights,
                "device": self.device, "fp16": self.fp16, "normalize": "siglip (0.5, 0.5)"}
