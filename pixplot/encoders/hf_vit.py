"""Base commune des encodeurs ViT chargés depuis Hugging Face (DINOv2, DINOv3).

``transformers`` télécharge les poids au premier usage dans le cache Hugging Face
(jamais dans le dépôt). Pour un modèle à accès restreint (DINOv3), il faut avoir accepté
la licence sur la page du modèle et être connecté (``hf auth login``).
"""

from __future__ import annotations

import numpy as np

from .base import EncodedBatch, Encoder


def split_tokens(hidden, n_registers: int, grid: int):
    """Séquence de sortie ViT (N, 1 + registres + grid², D) → (CLS (N, D), patchs (N, grid, grid, D)).

    Fonctionne aussi bien sur des tenseurs torch que sur des tableaux NumPy.
    """
    cls = hidden[:, 0]
    patches = hidden[:, 1 + n_registers:]
    if patches.shape[1] != grid * grid:
        raise ValueError(f"{patches.shape[1]} patchs reçus, {grid * grid} attendus (grille {grid}×{grid})")
    return cls, patches.reshape(patches.shape[0], grid, grid, patches.shape[-1])


class HFViTEncoder(Encoder):
    """Encodeur ViT générique : token CLS normalisé + grille de patchs, sans registres."""

    source = "huggingface"

    def __init__(self, name: str, hf_model: str, dim: int, patch_size: int,
                 input_size: int = 448, device: str | None = None, fp16: bool = True,
                 _load: bool = True):
        import torch  # import tardif : le reste de pixplot fonctionne sans torch

        if input_size % patch_size:
            raise ValueError(f"input_size doit être un multiple de {patch_size} pour {name}")
        self.name, self.dim, self.patch_size, self.input_size = name, dim, patch_size, input_size
        self.weights = hf_model
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.fp16 = fp16 and self.device != "cpu"
        self._torch = torch
        if _load:
            self.model = self._load_hf(hf_model)
            self.n_registers = int(getattr(self.model.config, "num_register_tokens", 0) or 0)
            self._finish_init()

    def _load_hf(self, hf_model: str):
        try:
            from transformers import AutoModel
        except ImportError as exc:
            raise ImportError("Installez transformers : pip install -e \".[ml]\"") from exc
        try:
            return AutoModel.from_pretrained(hf_model)
        except OSError as exc:
            raise OSError(
                f"Impossible de charger {hf_model}. Si le modèle est à accès restreint, vérifiez "
                f"que la licence est acceptée ET validée sur https://huggingface.co/{hf_model} "
                f"et que vous êtes connecté (`hf auth login`)."
            ) from exc

    def _finish_init(self) -> None:
        self.model.eval().to(self.device)
        if self.device != "cpu":
            self._torch.cuda.reset_peak_memory_stats()

    def _forward(self, x):
        """Renvoie (cls, patches) en tenseurs torch. Surchargé pour d'autres formats de poids."""
        hidden = self.model(pixel_values=x).last_hidden_state  # déjà normalisé (LayerNorm finale)
        return split_tokens(hidden, self.n_registers, self.input_size // self.patch_size)

    def encode(self, batch: np.ndarray) -> EncodedBatch:
        torch = self._torch
        x = torch.from_numpy(batch).to(self.device, non_blocking=True)
        with torch.inference_mode(), torch.autocast(
            device_type="cuda" if self.device != "cpu" else "cpu",
            dtype=torch.float16,
            enabled=self.fp16,
        ):
            cls, patches = self._forward(x)
        cls = torch.nn.functional.normalize(cls.float(), dim=-1)
        return EncodedBatch(global_vectors=cls.cpu().numpy(), patch_grid=patches.float().cpu().numpy())

    def runtime_stats(self) -> dict:
        if self.device == "cpu":
            return {"device": "cpu"}
        torch = self._torch
        return {
            "device": torch.cuda.get_device_name(0),
            "vram_peak_mib": round(torch.cuda.max_memory_allocated() / 2**20),
        }

    def describe(self) -> dict:
        return {**super().describe(), "source": self.source, "weights": str(self.weights),
                "device": self.device, "fp16": self.fp16}
