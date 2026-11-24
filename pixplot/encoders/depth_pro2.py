"""Encodeur Depth Pro 2 (Apple, nov. 2026) — candidat évalué pour la composition par les plans en
profondeur, en comparaison directe avec Depth Anything V2 (§ 28).

Licences :
- Code de référence (``apple-aiml-research/ml-depth-pro-2``) : licence Apple Sample Code.
- Poids Hugging Face (``apple/DepthPro2-{S,B,L}``) : **Apple Machine Learning Research Model
  License (apple-amlr)**, usage de recherche non commercial uniquement, accès public sans
  formulaire.

Architecture : tronc commun DINOv3 (``timm``) à patchs 16 × 16 + pyramide 4 niveaux + décodeur
DPT + tête de profondeur inverse (disparité normalisée par la focale, valeurs plus grandes pour
les plans proches). Pour des œuvres fixes indépendantes (une image = 1 vue), les blocs
``cross_frame`` opèrent image par image en préservant les jetons préfixes (CLS + registres),
ce qui est strictement équivalent au mode image unique du dépôt officiel tout en permettant le
traitement par lots sur GPU sans dépendance vidéo (ni ``av``, ni ``pillow-heif``).

Prétraitement : œuvre entière mise au carré par bandes neutres (letterbox, normalisation
ImageNet) à 512 px (multiple de 32, proche des 518 px de Depth Anything V2).
Descripteur : identique à ``depth.py`` — profondeur inverse recadrée sur l'œuvre seule, moyennée
sur une grille 8 × 8, centrée et normalisée L2 (z-score de norme 1 ; le cosinus vaut la
corrélation de Pearson entre les deux grilles).
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

from .base import EncodedBatch, Encoder
from .depth import DEFAULT_GRID, _crop_bounds

# (repo_id HF, backbone timm, blocs pyramide, blocs cross-frame, canaux pyramide, dim décodeur)
MODELS: dict[str, tuple[str, str, tuple[int, int, int, int], tuple[int, ...], tuple[int, int, int, int], int]] = {
    "depth_pro2_small": (
        "apple/DepthPro2-S",
        "vit_small_patch16_dinov3",
        (2, 5, 8, 11),
        (5, 7, 9, 11),
        (48, 96, 192, 384),
        64,
    ),
    "depth_pro2_base": (
        "apple/DepthPro2-B",
        "vit_base_patch16_dinov3",
        (2, 5, 8, 11),
        (5, 7, 9, 11),
        (96, 192, 384, 768),
        128,
    ),
    "depth_pro2_large": (
        "apple/DepthPro2-L",
        "vit_large_patch16_dinov3.lvd1689m",
        (5, 11, 17, 23),
        (9, 11, 13, 15, 17, 19, 21, 23),
        (256, 512, 1024, 1024),
        256,
    ),
}
DEFAULT_INPUT_SIZE = 512
INPUT_MULTIPLE = 32


def _build_depth_pro2_module(
    backbone_preset: str,
    reassembled_blocks: Sequence[int],
    cross_frame_blocks: Sequence[int],
    dims_reassemble: Sequence[int],
    dim_decoder: int,
):
    """Construit le module PyTorch Depth Pro 2 (image unique par lots, clés identiques au checkpoint HF)."""
    import timm
    import torch
    from torch import nn

    class ResidualBlock(nn.Module):
        def __init__(self, residual: nn.Module):
            super().__init__()
            self.residual = residual

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            return x + self.residual(x)

    class FeatureFusionBlock2d(nn.Module):
        def __init__(self, dim: int, with_skip: bool):
            super().__init__()
            if with_skip:
                self.resnet1 = self._residual_block(dim)
            self.resnet2 = self._residual_block(dim)
            self.deconv = nn.ConvTranspose2d(dim, dim, kernel_size=2, stride=2, bias=False)
            self.out_conv = nn.Conv2d(dim, dim, kernel_size=1)

        def forward(self, x: torch.Tensor, skip: torch.Tensor | None = None) -> torch.Tensor:
            if skip is not None:
                x = x + self.resnet1(skip)
            x = self.resnet2(x)
            x = self.deconv(x)
            return self.out_conv(x)

        @staticmethod
        def _residual_block(dim: int) -> ResidualBlock:
            return ResidualBlock(
                nn.Sequential(
                    nn.ReLU(),
                    nn.Conv2d(dim, dim, kernel_size=3, padding=1),
                    nn.ReLU(),
                    nn.Conv2d(dim, dim, kernel_size=3, padding=1),
                )
            )

    class DPTDecoder(nn.Module):
        def __init__(self, dims: Sequence[int], dim_dec: int):
            super().__init__()
            self.dim_out = dim_dec
            n_levels = len(dims)
            self.convs = nn.ModuleList(
                [nn.Conv2d(d, dim_dec, kernel_size=3, padding=1, bias=False) for d in dims]
            )
            self.fusions = nn.ModuleList(
                [FeatureFusionBlock2d(dim_dec, with_skip=i < n_levels - 1) for i in range(n_levels)]
            )

        def forward(self, encodings: Sequence[torch.Tensor]) -> torch.Tensor:
            feat = self.fusions[-1](self.convs[-1](encodings[-1]))
            for i in range(len(encodings) - 2, -1, -1):
                feat = self.fusions[i](feat, self.convs[i](encodings[i]))
            return feat

    class SingleImageEncoder(nn.Module):
        def __init__(self):
            super().__init__()
            vit = timm.create_model(
                backbone_preset, pretrained=False, num_classes=0, dynamic_img_size=True
            )
            vit.rope.normalize_coords = "max"
            self.patch_embed = vit.patch_embed
            self.cls_token = vit.cls_token
            self.reg_token = vit.reg_token
            self.rope = vit.rope
            self.blocks = vit.blocks
            self.embed_dim: int = vit.embed_dim
            self.patch_size: int = vit.patch_embed.patch_size[0]
            self.num_prefix_tokens: int = vit.num_prefix_tokens
            self.reassembled_blocks = tuple(reassembled_blocks)
            self.cross_frame_blocks = frozenset(cross_frame_blocks)
            dim = self.embed_dim
            self.reassemble = nn.ModuleList(
                [
                    nn.Sequential(
                        nn.Conv2d(dim, dims_reassemble[0], kernel_size=1),
                        nn.ConvTranspose2d(dims_reassemble[0], dims_reassemble[0], kernel_size=4, stride=4),
                    ),
                    nn.Sequential(
                        nn.Conv2d(dim, dims_reassemble[1], kernel_size=1),
                        nn.ConvTranspose2d(dims_reassemble[1], dims_reassemble[1], kernel_size=2, stride=2),
                    ),
                    nn.Sequential(nn.Conv2d(dim, dims_reassemble[2], kernel_size=1)),
                    nn.Sequential(
                        nn.Conv2d(dim, dims_reassemble[3], kernel_size=1),
                        nn.Conv2d(dims_reassemble[3], dims_reassemble[3], kernel_size=3, stride=2, padding=1),
                    ),
                ]
            )

        def forward(self, x: torch.Tensor) -> list[torch.Tensor]:
            grid_size = (x.shape[-2] // self.patch_size, x.shape[-1] // self.patch_size)
            rope = self.rope.get_embed(shape=grid_size)
            tokens = self.patch_embed(x).flatten(1, 2)
            bsz = tokens.shape[0]
            tokens = torch.cat(
                [self.cls_token.expand(bsz, -1, -1), self.reg_token.expand(bsz, -1, -1), tokens],
                dim=1,
            )
            npt = self.num_prefix_tokens
            tapped = []
            for idx, block in enumerate(self.blocks):
                if idx in self.cross_frame_blocks:
                    # En mode image unique (T=1), cross_frame_attention garde les jetons préfixes inchangés.
                    prefix = tokens[:, :npt]
                    out = block(tokens, rope=rope)
                    tokens = torch.cat([prefix, out[:, npt:]], dim=1)
                else:
                    tokens = block(tokens, rope=rope)
                if idx in self.reassembled_blocks:
                    tapped.append(tokens[:, npt:])
            return [
                layer(feat.transpose(1, 2).reshape(bsz, -1, *grid_size).contiguous())
                for layer, feat in zip(self.reassemble, tapped)
            ]

    class DepthPro2Module(nn.Module):
        def __init__(self):
            super().__init__()
            self.encoder = SingleImageEncoder()
            self.decoder = DPTDecoder(dims_reassemble, dim_decoder)
            self.head = nn.Sequential(
                nn.Conv2d(dim_decoder, dim_decoder // 2, kernel_size=3, padding=1),
                nn.ConvTranspose2d(dim_decoder // 2, dim_decoder // 2, kernel_size=2, stride=2),
                nn.Conv2d(dim_decoder // 2, 32, kernel_size=3, padding=1),
                nn.ReLU(True),
                nn.Conv2d(32, 1, kernel_size=1),
                nn.ReLU(),
            )

        def forward(self, x: torch.Tensor, autocast_dtype: torch.dtype | None = None) -> torch.Tensor:
            use_amp = autocast_dtype is not None and autocast_dtype != torch.float32 and x.device.type != "cpu"
            with torch.autocast(device_type=x.device.type, dtype=autocast_dtype or torch.float32, enabled=use_amp):
                decoded = self.decoder(self.encoder(x))
            return self.head(decoded.float())[:, 0]

    return DepthPro2Module()


class DepthPro2Encoder(Encoder):
    patch_size = None   # descripteur de disposition global (grille 8 × 8)
    needs_boxes = True  # demande les boîtes letterbox à extract.py pour ignorer les bandes

    def __init__(
        self,
        arch: str = "depth_pro2_base",
        hf_model: str | None = None,
        input_size: int | None = None,
        grid: int = DEFAULT_GRID,
        device: str | None = None,
        fp16: bool = True,
        model=None,
    ):
        import torch

        if arch not in MODELS:
            raise ValueError(f"Architecture inconnue : {arch} (choix : {', '.join(MODELS)})")
        if grid < 1:
            raise ValueError(f"grid doit être >= 1, reçu {grid}")

        repo_id, backbone, reas_blocks, cf_blocks, dims_reas, dim_dec = MODELS[arch]
        self.name = arch
        self.grid = grid
        self.dim = grid * grid
        self.input_size = input_size or DEFAULT_INPUT_SIZE
        if self.input_size % INPUT_MULTIPLE:
            raise ValueError(
                f"input_size doit être un multiple de {INPUT_MULTIPLE} (reçu {self.input_size})"
            )
        self.weights = hf_model or repo_id
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.fp16 = fp16 and self.device != "cpu"
        # Depth Pro 2 est entraîné et évalué en bfloat16 sur GPU (tête en float32).
        if self.fp16:
            bf16_ok = getattr(torch.cuda, "is_bf16_supported", lambda: False)()
            self.amp_dtype = torch.bfloat16 if bf16_ok else torch.float16
        else:
            self.amp_dtype = torch.float32
        self._torch = torch

        if model is None:
            from huggingface_hub import hf_hub_download
            from safetensors.torch import load_file

            mod = _build_depth_pro2_module(backbone, reas_blocks, cf_blocks, dims_reas, dim_dec)
            weights_path = hf_hub_download(self.weights, "model.safetensors")
            state = load_file(weights_path, device="cpu")
            mod.load_state_dict(state, strict=True)
            self.model = mod.eval().to(self.device)
        else:
            self.model = model.eval().to(self.device)

        if self.device != "cpu":
            torch.cuda.reset_peak_memory_stats()

    def predict_maps(self, batch: np.ndarray) -> np.ndarray:
        """Retourne les cartes de profondeur inverse ``(B, H, W)`` en float32 (utile pour l'examen visuel)."""
        torch = self._torch
        x = torch.from_numpy(np.ascontiguousarray(batch)).to(self.device, non_blocking=True)
        with torch.inference_mode():
            depth = self._forward(x)
        return depth.float().cpu().numpy()

    def _forward(self, x):
        try:
            out = self.model(x, autocast_dtype=self.amp_dtype)
        except TypeError:
            out = self.model(x)
        if hasattr(out, "predicted_depth"):
            out = out.predicted_depth
        out = out.float()
        if out.ndim == 4 and out.shape[1] == 1:
            out = out[:, 0]
        return out

    def encode(
        self,
        batch: np.ndarray,
        boxes: Sequence[tuple[int, int, int, int]] | None = None,
    ) -> EncodedBatch:
        torch = self._torch
        F = torch.nn.functional

        x = torch.from_numpy(np.ascontiguousarray(batch)).to(self.device, non_blocking=True)
        with torch.inference_mode():
            depth = self._forward(x)

        n, h_map, w_map = depth.shape
        grids = torch.empty((n, self.dim), device=depth.device, dtype=torch.float32)
        for i in range(n):
            box = boxes[i] if boxes is not None else None
            y0, y1, x0, x1 = _crop_bounds(box, self.input_size, h_map, w_map)
            crop = depth[i:i + 1, y0:y1, x0:x1].unsqueeze(1)
            grids[i] = F.adaptive_avg_pool2d(crop, (self.grid, self.grid)).reshape(-1)

        grids64 = grids.double()
        centered = grids64 - grids64.mean(dim=-1, keepdim=True)
        norms = centered.norm(dim=-1, keepdim=True)
        tol = 1e-6 * grids64.abs().mean(dim=-1, keepdim=True).clamp(min=1.0)
        vecs = torch.where(norms > tol, centered / norms.clamp(min=1e-12), torch.zeros_like(centered))
        return EncodedBatch(global_vectors=vecs.float().cpu().numpy())

    def runtime_stats(self) -> dict:
        if self.device == "cpu":
            return {"device": "cpu"}
        torch = self._torch
        return {
            "device": torch.cuda.get_device_name(0),
            "vram_peak_mib": round(torch.cuda.max_memory_allocated() / 2**20),
            "amp_dtype": str(self.amp_dtype).replace("torch.", ""),
        }

    def describe(self) -> dict:
        return {
            **super().describe(),
            "source": "huggingface",
            "weights": self.weights,
            "grid": self.grid,
            "descriptor": "zscore_grid_artwork",
            "device": self.device,
            "fp16": self.fp16,
        }
