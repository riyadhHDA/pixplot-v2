"""Encodeur DINOv3 (Meta) — le modèle principal de PixPlot v2.

1. **Hugging Face** (par défaut) : poids téléchargés automatiquement, après acceptation
   ET validation par Meta de la licence sur la page du modèle, et ``hf auth login``.
   Chaque taille (S, B, L) a sa propre demande d'accès.
2. **Format Meta** (secours) : dépôt cloné dans ``vendor/dinov3`` + fichier ``.pth``
   (obtenu via le formulaire de Meta), activé en passant ``weights=...``.

En attendant la validation, DINOv2 (sans demande d'accès) permet de commencer.
Pas encore exécuté sur la 7900 GRE.
"""

from __future__ import annotations

from pathlib import Path

from .hf_vit import HFViTEncoder, split_tokens  # noqa: F401  (split_tokens réexporté)

ARCH_DIMS = {"dinov3_vits16": 384, "dinov3_vitb16": 768, "dinov3_vitl16": 1024}
HF_MODELS = {
    "dinov3_vits16": "facebook/dinov3-vits16-pretrain-lvd1689m",
    "dinov3_vitb16": "facebook/dinov3-vitb16-pretrain-lvd1689m",
    "dinov3_vitl16": "facebook/dinov3-vitl16-pretrain-lvd1689m",
}


class DINOv3Encoder(HFViTEncoder):
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
        if arch not in ARCH_DIMS:
            raise ValueError(f"Architecture inconnue : {arch} (choix : {', '.join(ARCH_DIMS)})")
        use_meta = weights is not None
        super().__init__(arch, hf_model or HF_MODELS[arch], ARCH_DIMS[arch], 16,
                         input_size=input_size, device=device, fp16=fp16, _load=not use_meta)
        if use_meta:
            self.source = "meta"
            self.weights = Path(weights)
            repo = Path(repo)
            if not self.weights.exists():
                raise FileNotFoundError(f"Poids introuvables : {self.weights} (voir docs/INSTALL_GPU.md)")
            if not (repo / "hubconf.py").exists():
                raise FileNotFoundError(f"Dépôt DINOv3 introuvable : {repo} (voir docs/INSTALL_GPU.md)")
            self.model = self._torch.hub.load(str(repo), arch, source="local", weights=str(self.weights))
            self.n_registers = 0
            self._finish_init()

    def _forward(self, x):
        if self.source != "meta":
            return super()._forward(x)
        feats = self.model.forward_features(x)  # registres déjà retirés
        g = self.input_size // self.patch_size
        return feats["x_norm_clstoken"], feats["x_norm_patchtokens"].reshape(x.shape[0], g, g, -1)

    def describe(self) -> dict:
        d = super().describe()
        if self.source == "meta":
            d["weights"] = Path(self.weights).name
        return d
