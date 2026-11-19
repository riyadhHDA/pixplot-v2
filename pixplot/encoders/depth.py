"""Encodeur Depth Anything V2 (NeurIPS 2024, licence Apache 2.0 pour la variante Small) —
candidat évalué pour la composition par l'agencement des plans en profondeur.

Depth Anything V2 Small (``depth-anything/Depth-Anything-V2-Small-hf``, backbone DINOv2 ViT-S/14
et tête DPT, licence Apache 2.0 ; les variantes Base et Large sont sous CC BY-NC 4.0 et ne sont
pas incluses) prédit une carte de profondeur relative (disparité affine-invariante : valeurs plus
grandes pour les plans proches).

Prétraitement : œuvre entière mise au carré par bandes neutres (letterbox, normalisation ImageNet)
à la résolution native de 518 px (37 × 14).
Descripteur : la carte de profondeur est recadrée sur la seule zone de l'œuvre (bandes du letterbox
ignorées), moyennée sur une grille 8 × 8 calée sur l'œuvre, puis centrée et normalisée L2 par œuvre
(z-score de norme 1 : invariant à l'échelle et au décalage de la profondeur relative ; le cosinus
entre deux œuvres vaut exactement la corrélation de Pearson entre leurs grilles 8 × 8).
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np

from .base import EncodedBatch, Encoder

# Seule la variante Small est sous licence Apache 2.0 (Base et Large sont sous CC BY-NC 4.0).
MODELS: dict[str, tuple[str, int, int]] = {
    "depth_anything_v2_small": ("depth-anything/Depth-Anything-V2-Small-hf", 518, 14),
}
DEFAULT_GRID = 8


def _crop_bounds(
    box: tuple[int, int, int, int] | None,
    input_size: int,
    height: int,
    width: int,
) -> tuple[int, int, int, int]:
    """Convertit la boîte letterbox (left, top, w, h) en bornes (y0, y1, x0, x1) sur la carte."""
    if box is None:
        return 0, height, 0, width
    left, top, w, h = box
    sx = width / input_size
    sy = height / input_size
    x0 = max(0, min(width - 1, int(round(left * sx))))
    y0 = max(0, min(height - 1, int(round(top * sy))))
    x1 = max(x0 + 1, min(width, int(round((left + w) * sx))))
    y1 = max(y0 + 1, min(height, int(round((top + h) * sy))))
    return y0, y1, x0, x1


def depth_grid_descriptor(
    depth_map: np.ndarray,
    box: tuple[int, int, int, int] | None = None,
    input_size: int | None = None,
    grid: int = DEFAULT_GRID,
) -> np.ndarray:
    """Carte de profondeur 2D → vecteur (grid²,) normalisé (z-score de longueur 1) sur l'œuvre seule.

    Utilise exactement le découpage d'un ``adaptive_avg_pool2d`` (fonctionne aussi sans PyTorch
    et pour toute proportion d'œuvre, même très allongée).
    """
    if depth_map.ndim != 2:
        raise ValueError(f"depth_map doit être 2D, reçu {depth_map.shape}")
    h_map, w_map = depth_map.shape
    size = input_size or max(h_map, w_map)
    y0, y1, x0, x1 = _crop_bounds(box, size, h_map, w_map)
    crop = np.asarray(depth_map[y0:y1, x0:x1], dtype=np.float32)
    ch, cw = crop.shape

    cells = np.empty((grid, grid), dtype=np.float32)
    for r in range(grid):
        ry0 = (r * ch) // grid
        ry1 = max(ry0 + 1, math.ceil(((r + 1) * ch) / grid))
        for c in range(grid):
            cx0 = (c * cw) // grid
            cx1 = max(cx0 + 1, math.ceil(((c + 1) * cw) / grid))
            cells[r, c] = float(crop[ry0:ry1, cx0:cx1].mean())

    vec = cells.reshape(-1).astype(np.float64)
    vec = vec - vec.mean()
    norm = float(np.linalg.norm(vec))
    if norm <= 1e-6 * max(1.0, float(np.abs(cells).mean())):
        return np.zeros(grid * grid, dtype=np.float32)
    return (vec / norm).astype(np.float32)


class DepthAnythingEncoder(Encoder):
    patch_size = None  # descripteur de disposition global (grille 8 × 8)
    needs_boxes = True  # demande les boîtes letterbox à extract.py pour ignorer les bandes

    def __init__(
        self,
        arch: str = "depth_anything_v2_small",
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
        default_id, default_size, patch = MODELS[arch]
        self.name = arch
        self.grid = grid
        self.dim = grid * grid
        self.input_size = input_size or default_size
        if self.input_size % patch:
            raise ValueError(f"input_size doit être un multiple de {patch} (reçu {self.input_size})")
        self.weights = hf_model or default_id
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.fp16 = fp16 and self.device != "cpu"
        self._torch = torch

        if model is None:
            from transformers import AutoModelForDepthEstimation

            self.model = AutoModelForDepthEstimation.from_pretrained(self.weights).eval().to(self.device)
        else:
            self.model = model.eval().to(self.device)
        if self.device != "cpu":
            torch.cuda.reset_peak_memory_stats()

    def encode(
        self,
        batch: np.ndarray,
        boxes: Sequence[tuple[int, int, int, int]] | None = None,
    ) -> EncodedBatch:
        torch = self._torch
        F = torch.nn.functional

        x = torch.from_numpy(np.ascontiguousarray(batch)).to(self.device, non_blocking=True)
        with torch.inference_mode(), torch.autocast(
            device_type="cuda" if self.device != "cpu" else "cpu",
            dtype=torch.float16,
            enabled=self.fp16,
        ):
            out = self.model(pixel_values=x)
        depth = (out.predicted_depth if hasattr(out, "predicted_depth") else out).float()
        if depth.ndim == 4 and depth.shape[1] == 1:
            depth = depth[:, 0]

        n, h_map, w_map = depth.shape
        grids = torch.empty((n, self.dim), device=depth.device, dtype=torch.float32)
        for i in range(n):
            box = boxes[i] if boxes is not None else None
            y0, y1, x0, x1 = _crop_bounds(box, self.input_size, h_map, w_map)
            crop = depth[i:i + 1, y0:y1, x0:x1].unsqueeze(1)
            pooled = F.adaptive_avg_pool2d(crop, (self.grid, self.grid)).reshape(-1)
            grids[i] = pooled

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
