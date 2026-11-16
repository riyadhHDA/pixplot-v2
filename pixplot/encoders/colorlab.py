"""Encodeur « couleur » : la palette de l'œuvre, dans l'espace CIELAB (perceptuel).

Histogramme 5 (clarté) × 7 (a, vert-rouge) × 7 (b, bleu-jaune) = 245 cases, racine carrée
(atténue les grands aplats), bandes letterbox exclues. Sans GPU ni modèle.

Il ne comprend ni formes ni sujets : il répond à « quelles œuvres ont cette palette ? ».
"""

from __future__ import annotations

import numpy as np

from .base import IMAGENET_MEAN, IMAGENET_STD, EncodedBatch, Encoder

L_BINS, A_BINS, B_BINS = 5, 7, 7
PAD_EPS = 0.03
_M = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]], np.float32)
_WHITE = np.array([0.95047, 1.0, 1.08883], np.float32)


def rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """(..., 3) sRGB dans [0, 1] → (..., 3) L*a*b*."""
    lin = np.where(rgb > 0.04045, ((rgb + 0.055) / 1.055) ** 2.4, rgb / 12.92)
    xyz = (lin @ _M.T) / _WHITE
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


class ColorLabEncoder(Encoder):
    name = "color_lab"
    input_size = 224
    patch_size = None
    center_after = True

    def __init__(self):
        self.dim = L_BINS * A_BINS * B_BINS

    def encode(self, batch: np.ndarray) -> EncodedBatch:
        mean = np.array(IMAGENET_MEAN, np.float32)
        std = np.array(IMAGENET_STD, np.float32)
        x = batch.transpose(0, 2, 3, 1)                       # (N, S, S, 3)
        pad = np.abs(x).max(axis=-1) < PAD_EPS
        lab = rgb_to_lab(np.clip(x * std + mean, 0, 1))
        qL = np.clip((lab[..., 0] / 100 * L_BINS).astype(int), 0, L_BINS - 1)
        qa = np.clip(((lab[..., 1] + 60) / 120 * A_BINS).astype(int), 0, A_BINS - 1)
        qb = np.clip(((lab[..., 2] + 60) / 120 * B_BINS).astype(int), 0, B_BINS - 1)
        code = (qL * A_BINS + qa) * B_BINS + qb
        out = np.zeros((len(batch), self.dim), np.float32)
        for n in range(len(batch)):
            c = code[n][~pad[n]]
            if c.size:
                h = np.bincount(c, minlength=self.dim).astype(np.float32)
                out[n] = np.sqrt(h / h.sum())
        out /= np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-12)
        return EncodedBatch(global_vectors=out, patch_grid=None)
