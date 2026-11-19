"""Encodeur CSD (Contrastive Style Descriptors, Somepalli et al., ECCV 2024) — candidat pour « touche ».

CSD (*Measuring Style Similarity in Diffusion Models*, arXiv:2404.01292) part d'un encodeur visuel
CLIP ViT-L/14 affiné par apprentissage contrastif multi-étiquettes sur LAION-Styles (511 921 images
tirées de LAION-Aesthetics 6+, 3 840 étiquettes d'artistes, médiums et mouvements) avec deux têtes
linéaires (style et contenu). On utilise la sortie ``style`` normalisée L2 (768 dimensions).

Licences vérifiées avant téléchargement :
- code officiel (``learn2phoenix/CSD``) : licence **MIT** ;
- poids publiés sur Hugging Face (``tomg-group-umd/CSD-ViT-L``) : licence **CC BY 4.0** (accès libre).

Implémentation autonome en PyTorch (sans dépendance au paquet ``openai/clip``) fidèle au
``VisionTransformer`` ViT-L/14 d'OpenAI CLIP (QuickGELU, normalisation CLIP) et à ``CSD_CLIP``.
Prétraitement : œuvre entière en *letterbox* (sans recadrage), fond à la moyenne CLIP, 224 px.
Pas de vecteurs régionaux.
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

import numpy as np
from PIL import Image

from .base import EncodedBatch, Encoder, letterbox, letterbox_box

CLIP_MEAN = (0.48145466, 0.4578275, 0.40821073)
CLIP_STD = (0.26862954, 0.26130258, 0.27577711)
CLIP_PAD_RGB = tuple(round(m * 255) for m in CLIP_MEAN)

# arch → (dépôt HF, fichier, dim sortie, résolution, patch, width, layers, heads)
MODELS: dict[str, tuple[str, str, int, int, int, int, int, int]] = {
    "csd_vitl14": ("tomg-group-umd/CSD-ViT-L", "pytorch_model.bin", 768, 224, 14, 1024, 24, 16),
}


def build_csd_model(
    torch,
    *,
    input_resolution: int = 224,
    patch_size: int = 14,
    width: int = 1024,
    layers: int = 24,
    heads: int = 16,
    output_dim: int = 768,
):
    """Backbone CLIP ViT-L/14 + tête de projection style CSD (296 paramètres hors tête contenu)."""
    nn = torch.nn

    class _QuickGELU(nn.Module):
        def forward(self, x):
            return x * torch.sigmoid(1.702 * x)

    class _ResBlock(nn.Module):
        def __init__(self):
            super().__init__()
            self.attn = nn.MultiheadAttention(width, heads, batch_first=True)
            self.ln_1 = nn.LayerNorm(width)
            self.mlp = nn.Sequential(OrderedDict([
                ("c_fc", nn.Linear(width, width * 4)),
                ("gelu", _QuickGELU()),
                ("c_proj", nn.Linear(width * 4, width)),
            ]))
            self.ln_2 = nn.LayerNorm(width)

        def forward(self, x):
            h = self.ln_1(x)
            x = x + self.attn(h, h, h, need_weights=False)[0]
            return x + self.mlp(self.ln_2(x))

    class _Transformer(nn.Module):
        def __init__(self):
            super().__init__()
            self.resblocks = nn.Sequential(*[_ResBlock() for _ in range(layers)])

        def forward(self, x):
            return self.resblocks(x)

    class _CLIPBackbone(nn.Module):
        def __init__(self):
            super().__init__()
            grid = input_resolution // patch_size
            self.conv1 = nn.Conv2d(3, width, kernel_size=patch_size, stride=patch_size, bias=False)
            self.class_embedding = nn.Parameter(torch.empty(width))
            self.positional_embedding = nn.Parameter(torch.empty(grid * grid + 1, width))
            self.ln_pre = nn.LayerNorm(width)
            self.transformer = _Transformer()
            self.ln_post = nn.LayerNorm(width)

        def forward(self, x):
            x = self.conv1(x).flatten(2).transpose(1, 2)  # (N, L, W)
            cls = self.class_embedding.to(x.dtype).view(1, 1, -1).expand(x.shape[0], -1, -1)
            x = torch.cat([cls, x], dim=1) + self.positional_embedding.to(x.dtype)
            x = self.ln_pre(x)
            x = self.transformer(x)
            return self.ln_post(x[:, 0, :])

    class _CSDNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.backbone = _CLIPBackbone()
            self.last_layer_style = nn.Parameter(torch.empty(width, output_dim))

        def forward(self, x):
            feat = self.backbone(x)
            return feat @ self.last_layer_style.to(feat.dtype)

    return _CSDNet()


def preprocess_csd(image: Image.Image, size: int = 224) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """Image RGB orientée → (tableau (3, size, size) normalisé CLIP, boîte letterbox)."""
    box = letterbox_box(*image.size, size)
    canvas = letterbox(image, size, fill=CLIP_PAD_RGB)
    arr = np.asarray(canvas, dtype=np.float32) / 255.0
    mean = np.array(CLIP_MEAN, dtype=np.float32)
    std = np.array(CLIP_STD, dtype=np.float32)
    return ((arr - mean) / std).transpose(2, 0, 1), box


class CSDEncoder(Encoder):
    patch_size = None  # descripteur global de style uniquement

    def __init__(
        self,
        arch: str = "csd_vitl14",
        hf_model: str | None = None,
        weights: str | Path | None = None,
        input_size: int | None = None,
        device: str | None = None,
        fp16: bool = True,
        model=None,
    ):
        import torch

        if arch not in MODELS:
            raise ValueError(f"Architecture inconnue : {arch} (choix : {', '.join(MODELS)})")
        default_repo, filename, dim, size, patch, width, layers, heads = MODELS[arch]
        self.name = arch
        self.dim = dim
        self.input_size = input_size or size
        if self.input_size != size and model is None:
            raise ValueError(f"{arch} utilise des plongements positionnels fixes à {size} px (reçu {self.input_size})")
        self.weights = str(weights) if weights is not None else (hf_model or default_repo)
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.fp16 = fp16 and self.device != "cpu"
        self._torch = torch
        self.checkpoint_iter: int | None = None

        if model is not None:
            self.model = model.eval().to(self.device)
        else:
            if weights is not None:
                ckpt_path = Path(weights)
                if not ckpt_path.exists():
                    raise FileNotFoundError(f"Poids CSD introuvables : {ckpt_path}")
            else:
                from huggingface_hub import hf_hub_download
                ckpt_path = Path(hf_hub_download(hf_model or default_repo, filename))

            ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
            if isinstance(ckpt, dict) and "model_state_dict" in ckpt:
                if "iter" in ckpt:
                    self.checkpoint_iter = int(ckpt["iter"])
                raw_sd = ckpt["model_state_dict"]
            elif isinstance(ckpt, dict) and "state_dict" in ckpt:
                raw_sd = ckpt["state_dict"]
            else:
                raw_sd = ckpt

            sd = {}
            for k, v in raw_sd.items():
                clean = k.removeprefix("module.")
                if clean == "last_layer_content" or clean.startswith("last_layer_content."):
                    continue
                sd[clean] = v.float() if v.is_floating_point() else v

            net = build_csd_model(
                torch,
                input_resolution=self.input_size,
                patch_size=patch,
                width=width,
                layers=layers,
                heads=heads,
                output_dim=dim,
            )
            net.load_state_dict(sd, strict=True)
            self.model = net.eval().to(self.device)
            del ckpt, raw_sd, sd

        if self.device != "cpu":
            torch.cuda.reset_peak_memory_stats()

    def preprocess(self, image: Image.Image):
        return preprocess_csd(image, self.input_size)

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
        out = {
            **super().describe(),
            "source": "huggingface",
            "weights": self.weights,
            "device": self.device,
            "fp16": self.fp16,
            "normalize": "clip",
            "eval_embed": "style_head",
        }
        if self.checkpoint_iter is not None:
            out["checkpoint_iter"] = self.checkpoint_iter
        return out
