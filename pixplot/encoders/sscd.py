"""Encodeur SSCD (Meta, CVPR 2022, licence MIT) — candidat évalué pour le regard « copie ».

SSCD (*A Self-Supervised Descriptor for Image Copy Detection*, Pizzi et al., CVPR 2022) est
entraîné par apprentissage contrastif avec régularisation d'entropie différentielle pour
produire une empreinte normalisée L2 destinée à la détection de copies et d'images modifiées
(recadrages, filtres, superpositions, changements de résolution).

Poids TorchScript autonomes (licence MIT, dépôt ``facebookresearch/sscd-copy-detection``),
téléchargés dans le dossier de données (``<données>/models/``), jamais versionnés dans git :
- ``sscd_disc_mixup`` : ResNet-50, 512 dimensions ;
- ``sscd_disc_large`` : ResNeXt-101 32×4d, 1024 dimensions.

Prétraitement : œuvre entière mise au carré par bandes neutres (letterbox, normalisation
ImageNet), à 320 px par défaut (taille carrée recommandée par le dépôt pour l'inférence par
lots GPU ; surchargeable via ``input_size``, par ex. 288 px). Pas de vecteurs régionaux.
"""

from __future__ import annotations

import os
import urllib.request
from pathlib import Path

import numpy as np

from ..config import get_settings
from .base import EncodedBatch, Encoder

BASE_URL = "https://dl.fbaipublicfiles.com/sscd-copy-detection"
MODELS: dict[str, tuple[str, int, int]] = {
    "sscd_disc_mixup": (f"{BASE_URL}/sscd_disc_mixup.torchscript.pt", 512, 320),
    "sscd_disc_large": (f"{BASE_URL}/sscd_disc_large.torchscript.pt", 1024, 320),
}


def download_weights(arch: str, dest: Path) -> Path:
    """Télécharge le modèle TorchScript SSCD (licence MIT) de façon atomique s'il est absent."""
    if dest.exists():
        return dest
    url = MODELS[arch][0]
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        urllib.request.urlretrieve(url, tmp)
        os.replace(tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return dest


class SSCDEncoder(Encoder):
    patch_size = None  # descripteur global uniquement (pooling GeM)

    def __init__(
        self,
        arch: str = "sscd_disc_large",
        weights: str | Path | None = None,
        cache_dir: str | Path | None = None,
        input_size: int | None = None,
        device: str | None = None,
        fp16: bool = True,
    ):
        import torch

        if arch not in MODELS:
            raise ValueError(f"Architecture inconnue : {arch} (choix : {', '.join(MODELS)})")
        _, dim, default_size = MODELS[arch]
        self.name = arch
        self.dim = dim
        self.input_size = input_size or default_size
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.fp16 = fp16 and self.device != "cpu"
        self._torch = torch

        if weights is not None:
            path = Path(weights)
            if not path.exists():
                raise FileNotFoundError(f"Poids SSCD introuvables : {path}")
        else:
            root = Path(cache_dir) if cache_dir is not None else get_settings().data_dir / "models"
            path = download_weights(arch, root / f"{arch}.torchscript.pt")
        self.weights = path

        self.model = torch.jit.load(str(self.weights), map_location=self.device).eval()
        if self.device != "cpu":
            torch.cuda.reset_peak_memory_stats()

    def encode(self, batch: np.ndarray) -> EncodedBatch:
        torch = self._torch
        x = torch.from_numpy(np.ascontiguousarray(batch)).to(self.device, non_blocking=True)
        with torch.inference_mode(), torch.autocast(
            device_type="cuda" if self.device != "cpu" else "cpu",
            dtype=torch.float16,
            enabled=self.fp16,
        ):
            feats = self.model(x)
        feats = torch.nn.functional.normalize(feats.float(), dim=-1)
        return EncodedBatch(global_vectors=feats.cpu().numpy())

    def runtime_stats(self) -> dict:
        if self.device == "cpu":
            return {"device": "cpu"}
        torch = self._torch
        return {
            "device": torch.cuda.get_device_name(0),
            "vram_peak_mib": round(torch.cuda.max_memory_allocated() / 2**20),
        }

    def describe(self) -> dict:
        return {
            **super().describe(),
            "source": "meta-sscd",
            "weights": self.weights.name,
            "device": self.device,
            "fp16": self.fp16,
        }
