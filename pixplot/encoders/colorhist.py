"""Encodeur « histogramme de couleurs » : sans GPU, sans modèle à télécharger.

Sert à tester tout le pipeline sur n'importe quelle machine. Il donne aussi un premier
espace chromatique (palettes proches), mais il ne comprend ni formes ni sujets.
"""

from __future__ import annotations

import numpy as np

from .base import IMAGENET_MEAN, IMAGENET_STD, EncodedBatch, Encoder


class ColorHistEncoder(Encoder):
    name = "colorhist"
    input_size = 224
    patch_size = 16
    bins = 4  # 4×4×4 = 64 cases

    def __init__(self):
        self.dim = self.bins ** 3

    def encode(self, batch: np.ndarray) -> EncodedBatch:
        mean = np.array(IMAGENET_MEAN, dtype=np.float32)[None, :, None, None]
        std = np.array(IMAGENET_STD, dtype=np.float32)[None, :, None, None]
        rgb = np.clip(batch * std + mean, 0, 1)                      # (N, 3, S, S)
        q = np.minimum((rgb * self.bins).astype(np.int64), self.bins - 1)
        codes = (q[:, 0] * self.bins + q[:, 1]) * self.bins + q[:, 2]  # (N, S, S)

        n, s = codes.shape[0], codes.shape[1]
        g, ps = s // self.patch_size, self.patch_size
        # Comptage par patch sans tableau one-hot géant : un seul bincount.
        cells = codes.reshape(n, g, ps, g, ps).transpose(0, 1, 3, 2, 4).reshape(n * g * g, ps * ps)
        flat = (np.arange(n * g * g)[:, None] * self.dim + cells).ravel()
        counts = np.bincount(flat, minlength=n * g * g * self.dim)
        patches = (counts.reshape(n, g, g, self.dim) / (ps * ps)).astype(np.float32)

        hist = np.sqrt(patches.mean(axis=(1, 2)))  # racine : atténue les aplats dominants
        hist /= np.maximum(np.linalg.norm(hist, axis=1, keepdims=True), 1e-12)
        return EncodedBatch(global_vectors=hist.astype(np.float32), patch_grid=patches)
