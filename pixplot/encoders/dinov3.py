"""Encodeur DINOv3 (Meta), deux façons de charger les poids :

1. **Hugging Face** (par défaut) : ``transformers`` télécharge les poids tout seul.
   Il faut avoir accepté la licence sur la page du modèle et être connecté
   (``hf auth login``). Chaque taille (S, B, L) a sa propre demande d'accès.
2. **Format Meta** (secours) : dépôt cloné dans ``vendor/dinov3`` + fichier ``.pth``,
   activé en passant ``weights=...``.

Les deux donnent les mêmes sorties : token CLS normalisé et tokens de patchs normalisés,
sans les tokens « registres ». Voir docs/INSTALL_GPU.md. Pas encore exécuté sur la 7900 GRE.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .base import EncodedBatch, Encoder

ARCH_DIMS = {"dinov3_vits16": 384, "dinov3_vitb16": 768, "dinov3_vitl16": 1024}
HF_MODELS = {
    "dinov3_vits16": "facebook/dinov3-vits16-pretrain-lvd1689m",
    "dinov3_vitb16": "facebook/dinov3-vitb16-pretrain-lvd1689m",
    "dinov3_vitl16": "facebook/dinov3-vitl16-pretrain-lvd1689m",
}


def split_tokens(hidden, n_registers: int, grid: int):
    """Séquence de sortie ViT (N, 1 + registres + grid², D) → (CLS (N, D), patchs (N, grid, grid, D)).

    Fonctionne aussi bien sur des tenseurs torch que sur des tableaux NumPy.
    """
    cls = hidden[:, 0]
    patches = hidden[:, 1 + n_registers:]
    if patches.shape[1] != grid * grid:
        raise ValueError(f"{patches.shape[1]} patchs reçus, {grid * grid} attendus (grille {grid}×{grid})")
    return cls, patches.reshape(patches.shape[0], grid, grid, patches.shape[-1])


class DINOv3Encoder(Encoder):
    patch_size = 16

    def __init__(
        self,
        arch: str = "dinov3_vitb16",
        weights: str | Path | None = None,
        repo: str | Path = "vendor/dinov3",
        hf_model: str | None = None,
        input_size: int = 448,
        device: str | None = None,
        fp16: bool = True,
    ):
        import torch  # import tardif : le reste de pixplot fonctionne sans torch

        if arch not in ARCH_DIMS:
            raise ValueError(f"Architecture inconnue : {arch} (choix : {', '.join(ARCH_DIMS)})")
        if input_size % self.patch_size:
            raise ValueError("input_size doit être un multiple de 16")

        self.name = arch
        self.dim = ARCH_DIMS[arch]
        self.input_size = input_size
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.fp16 = fp16 and self.device != "cpu"
        self._torch = torch

        if weights is not None:
            self.source = "meta"
            self.weights = Path(weights)
            repo = Path(repo)
            if not self.weights.exists():
                raise FileNotFoundError(f"Poids introuvables : {self.weights} (voir docs/INSTALL_GPU.md)")
            if not (repo / "hubconf.py").exists():
                raise FileNotFoundError(f"Dépôt DINOv3 introuvable : {repo} (voir docs/INSTALL_GPU.md)")
            self.model = torch.hub.load(str(repo), arch, source="local", weights=str(self.weights))
            self.n_registers = None  # forward_features les retire déjà
        else:
            self.source = "huggingface"
            self.weights = hf_model or HF_MODELS[arch]
            try:
                from transformers import AutoModel
            except ImportError as exc:
                raise ImportError("Installez transformers : pip install -e \".[ml]\"") from exc
            try:
                self.model = AutoModel.from_pretrained(self.weights)
            except OSError as exc:
                raise OSError(
                    f"Impossible de charger {self.weights}. Vérifiez que la licence est acceptée "
                    f"et validée sur https://huggingface.co/{self.weights} et que vous êtes "
                    f"connecté (`hf auth login`)."
                ) from exc
            self.n_registers = int(getattr(self.model.config, "num_register_tokens", 0))

        self.model.eval().to(self.device)
        if self.device != "cpu":
            torch.cuda.reset_peak_memory_stats()

    def encode(self, batch: np.ndarray) -> EncodedBatch:
        torch = self._torch
        x = torch.from_numpy(batch).to(self.device, non_blocking=True)
        grid = self.input_size // self.patch_size

        with torch.inference_mode(), torch.autocast(
            device_type="cuda" if self.device != "cpu" else "cpu",
            dtype=torch.float16,
            enabled=self.fp16,
        ):
            if self.source == "meta":
                feats = self.model.forward_features(x)
                cls = feats["x_norm_clstoken"]
                patches = feats["x_norm_patchtokens"].reshape(x.shape[0], grid, grid, -1)
            else:
                hidden = self.model(pixel_values=x).last_hidden_state  # déjà normalisé (LayerNorm finale)
                cls, patches = split_tokens(hidden, self.n_registers, grid)

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
        weights = self.weights.name if isinstance(self.weights, Path) else self.weights
        return {**super().describe(), "source": self.source, "weights": weights,
                "device": self.device, "fp16": self.fp16}
