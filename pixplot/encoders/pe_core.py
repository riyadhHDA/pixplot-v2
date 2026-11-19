"""Encodeur PE-Core (Meta, Perception Encoder, 2025, licence Apache 2.0) — candidat pour « sujet ».

PE-Core est l'encodeur vision-langage de la famille Perception Encoder (Bolya et al., Meta, 2025,
arXiv:2504.13181) : images et textes sont projetés dans un même espace contrastif, ce qui permet à
la fois la recherche par ressemblance de sujet et la recherche par phrase.

Poids sous licence Apache 2.0 (accès libre sur Hugging Face, remappage OpenCLIP maintenu par
``timm`` : ``timm/PE-Core-L-14-336``, ``timm/PE-Core-B-16-224``, ``timm/PE-Core-bigG-14-448``).
La tour visuelle est chargée via ``timm`` (``vit_pe_core_*``) et la tour texte par un transformer
causal PyTorch fidèle à l'implémentation officielle (``facebookresearch/perception_models``),
sans dépendance externe supplémentaire (``open_clip`` n'est pas requis).

Prétraitement : œuvre entière conservée sans recadrage (letterbox), fond gris neutre (128),
normalisation ``(x - 0,5) / 0,5`` (identique à la configuration officielle de PE-Core et à SigLIP 2).
Pas de vecteurs régionaux : la recherche par détail passe par DINOv3.
"""

from __future__ import annotations

from collections import OrderedDict

import numpy as np
from PIL import Image

from .base import EncodedBatch, Encoder, letterbox, letterbox_box

# arch → (dépôt HF, modèle timm, dim, taille image, context_length, width texte, heads, layers)
MODELS: dict[str, tuple[str, str, int, int, int, int, int, int]] = {
    "pe_core_b16": ("timm/PE-Core-B-16-224", "vit_pe_core_base_patch16_224", 1024, 224, 32, 1024, 16, 24),
    "pe_core_l14": ("timm/PE-Core-L-14-336", "vit_pe_core_large_patch14_336", 1024, 336, 32, 1024, 16, 24),
    "pe_core_g14": ("timm/PE-Core-bigG-14-448", "vit_pe_core_gigantic_patch14_448", 1280, 448, 72, 1280, 20, 24),
}


def _build_text_tower(
    torch,
    *,
    vocab_size: int = 49408,
    context_length: int = 32,
    width: int = 1024,
    heads: int = 16,
    layers: int = 24,
    output_dim: int = 1024,
):
    """Tour texte causale de PE-Core (GELU standard, padding 0, pooling argmax sur EOT)."""
    nn = torch.nn

    class _ResBlock(nn.Module):
        def __init__(self):
            super().__init__()
            self.ln_1 = nn.LayerNorm(width, eps=1e-5)
            self.attn = nn.MultiheadAttention(width, heads, batch_first=True)
            self.ln_2 = nn.LayerNorm(width, eps=1e-5)
            self.mlp = nn.Sequential(OrderedDict([
                ("c_fc", nn.Linear(width, width * 4)),
                ("gelu", nn.GELU()),
                ("c_proj", nn.Linear(width * 4, width)),
            ]))

        def forward(self, x, attn_mask):
            h = self.ln_1(x)
            x = x + self.attn(h, h, h, need_weights=False, attn_mask=attn_mask)[0]
            return x + self.mlp(self.ln_2(x))

    class _Transformer(nn.Module):
        def __init__(self):
            super().__init__()
            self.resblocks = nn.ModuleList([_ResBlock() for _ in range(layers)])

        def forward(self, x, attn_mask):
            for blk in self.resblocks:
                x = blk(x, attn_mask)
            return x

    class _PETextTower(nn.Module):
        def __init__(self):
            super().__init__()
            self.context_length = context_length
            self.token_embedding = nn.Embedding(vocab_size, width)
            self.positional_embedding = nn.Parameter(torch.empty(context_length, width))
            self.transformer = _Transformer()
            self.ln_final = nn.LayerNorm(width, eps=1e-5)
            self.text_projection = nn.Parameter(torch.empty(width, output_dim))
            mask = torch.full((context_length, context_length), float("-inf")).triu(1)
            self.register_buffer("attn_mask", mask, persistent=False)

        def forward(self, tokens):
            seq_len = tokens.shape[1]
            x = self.token_embedding(tokens) + self.positional_embedding[:seq_len]
            mask = self.attn_mask[:seq_len, :seq_len].to(x.dtype)
            x = self.ln_final(self.transformer(x, mask))
            # Le jeton EOT (49407) a le plus grand identifiant de la séquence (padding à 0)
            pooled = x[torch.arange(x.shape[0], device=x.device), tokens.argmax(dim=-1)]
            return pooled @ self.text_projection

    return _PETextTower()


def tokenize_pe_core(tokenizer, texts: list[str], context_length: int) -> np.ndarray:
    """Encode des phrases pour PE-Core : BOS + jetons + EOT, complété par des zéros (pad_id=0)."""
    bos = int(tokenizer.bos_token_id)
    eos = int(tokenizer.eos_token_id)
    out = np.zeros((len(texts), context_length), dtype=np.int64)
    for row, text in enumerate(texts):
        ids = tokenizer.encode(text, add_special_tokens=False)
        seq = [bos] + ids[: context_length - 2] + [eos]
        out[row, : len(seq)] = seq
    return out


class PECoreEncoder(Encoder):
    patch_size = None  # pas de vecteurs régionaux

    def __init__(
        self,
        arch: str = "pe_core_l14",
        hf_model: str | None = None,
        input_size: int | None = None,
        device: str | None = None,
        fp16: bool = True,
        vision_model=None,
        text_model=None,
        tokenizer=None,
    ):
        import torch

        if arch not in MODELS:
            raise ValueError(f"Architecture inconnue : {arch} (choix : {', '.join(MODELS)})")
        default_repo, timm_name, dim, size, ctx_len, width, heads, layers = MODELS[arch]
        self.name = arch
        self.dim = dim
        self.input_size = input_size or size
        self.context_length = ctx_len
        self.weights = hf_model or default_repo
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.fp16 = fp16 and self.device != "cpu"
        self._torch = torch
        self._timm_name = timm_name
        self._text_cfg = (ctx_len, width, heads, layers, dim)

        if vision_model is not None:
            self.visual = vision_model.eval().to(self.device)
            self.text_model = text_model.eval().to(self.device) if text_model is not None else None
            self.tokenizer = tokenizer
            if text_model is not None and hasattr(text_model, "context_length"):
                self.context_length = int(text_model.context_length)
        else:
            import timm
            from huggingface_hub import hf_hub_download
            from safetensors.torch import load_file
            from transformers import AutoTokenizer

            ckpt_path = hf_hub_download(self.weights, "open_clip_model.safetensors")
            sd = load_file(ckpt_path, device="cpu")

            v_sd = {k.removeprefix("visual.trunk."): v for k, v in sd.items() if k.startswith("visual.trunk.")}
            visual = timm.create_model(
                timm_name, pretrained=False, num_classes=dim, img_size=self.input_size,
            )
            visual.load_state_dict(v_sd, strict=True)
            self.visual = visual.eval().to(self.device)

            t_sd = {k.removeprefix("text."): v for k, v in sd.items() if k.startswith("text.")}
            text_tower = _build_text_tower(
                torch,
                context_length=ctx_len,
                width=width,
                heads=heads,
                layers=layers,
                output_dim=dim,
            )
            text_tower.load_state_dict(t_sd, strict=True)
            self.text_model = text_tower.eval().to(self.device)
            self.tokenizer = AutoTokenizer.from_pretrained(self.weights)
            del sd, v_sd, t_sd

        if self.device != "cpu":
            torch.cuda.reset_peak_memory_stats()

    def preprocess(self, image: Image.Image):
        box = letterbox_box(*image.size, self.input_size)
        canvas = letterbox(image, self.input_size, fill=(128, 128, 128))
        arr = (np.asarray(canvas, dtype=np.float32) / 255.0 - 0.5) / 0.5
        return arr.transpose(2, 0, 1), box

    def _autocast(self):
        return self._torch.autocast(
            device_type="cuda" if self.device != "cpu" else "cpu",
            dtype=self._torch.float16,
            enabled=self.fp16,
        )

    def encode(self, batch: np.ndarray) -> EncodedBatch:
        torch = self._torch
        x = torch.from_numpy(np.ascontiguousarray(batch)).to(self.device, non_blocking=True)
        with torch.inference_mode(), self._autocast():
            feats = self.visual(x)
        feats = torch.nn.functional.normalize(feats.float(), dim=-1)
        return EncodedBatch(global_vectors=feats.cpu().numpy())

    def encode_text(self, texts: list[str]) -> np.ndarray:
        """Textes → vecteurs normalisés (N, D), comparables aux vecteurs d'images."""
        if self.text_model is None or self.tokenizer is None:
            raise RuntimeError("Tour texte PE-Core non chargée.")
        torch = self._torch
        arr = tokenize_pe_core(self.tokenizer, texts, self.context_length)
        tokens = torch.from_numpy(arr).to(self.device)
        with torch.inference_mode(), self._autocast():
            feats = self.text_model(tokens)
        return torch.nn.functional.normalize(feats.float(), dim=-1).cpu().numpy()

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
            "source": "huggingface",
            "weights": self.weights,
            "context_length": self.context_length,
            "device": self.device,
            "fp16": self.fp16,
            "normalize": "pe_core (0.5, 0.5)",
        }
