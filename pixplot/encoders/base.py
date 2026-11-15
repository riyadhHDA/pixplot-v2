"""Interface commune des modèles et prétraitement des images.

Règle d'or pour l'histoire de l'art : **on ne recadre jamais l'œuvre**. L'image entière
est réduite puis complétée par des bandes (letterbox) pour garder la composition.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np
from PIL import Image

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)
# Couleur des bandes = moyenne ImageNet : après normalisation elle vaut ~0,
# donc le modèle la « voit » le moins possible.
PAD_RGB = tuple(round(m * 255) for m in IMAGENET_MEAN)


def letterbox_box(width: int, height: int, size: int) -> tuple[int, int, int, int]:
    """Position (gauche, haut, largeur, hauteur) de l'œuvre dans le carré ``size``×``size``.

    Sert aussi à savoir quels patchs couvrent l'œuvre et lesquels couvrent les bandes.
    """
    scale = size / max(width, height)
    w = max(1, round(width * scale))
    h = max(1, round(height * scale))
    return (size - w) // 2, (size - h) // 2, w, h


def letterbox(image: Image.Image, size: int, fill: tuple[int, int, int] = PAD_RGB) -> Image.Image:
    """Redimensionne l'image entière dans un carré ``size``×``size`` sans la recadrer.

    L'orientation EXIF doit déjà être appliquée (voir ``pixplot.imageio.open_image``).
    """
    if image.mode != "RGB":
        image = image.convert("RGB")
    left, top, w, h = letterbox_box(*image.size, size)
    resized = image.resize((w, h), Image.Resampling.BICUBIC)
    canvas = Image.new("RGB", (size, size), fill)
    canvas.paste(resized, (left, top))
    return canvas


def to_normalized_array(image: Image.Image) -> np.ndarray:
    """PIL RGB → tableau float32 (3, H, W) normalisé ImageNet."""
    arr = np.asarray(image, dtype=np.float32) / 255.0
    arr = (arr - np.array(IMAGENET_MEAN, dtype=np.float32)) / np.array(IMAGENET_STD, dtype=np.float32)
    return arr.transpose(2, 0, 1)


@dataclass
class EncodedBatch:
    """Sortie d'un encodeur pour un lot de N images.

    global_vectors : (N, D) float32, normalisés L2.
    patch_grid     : (N, gh, gw, D) float32 ou None (vecteurs par zone).
    """

    global_vectors: np.ndarray
    patch_grid: np.ndarray | None = None


class Encoder(ABC):
    """Contrat que chaque modèle (DINOv3, SigLIP 2, futurs modèles) doit respecter.

    Le prétraitement (CPU, exécuté dans des threads de chargement) est séparé de
    l'encodage (GPU), pour que le GPU ne reste jamais à attendre les images.
    """

    name: str
    dim: int
    input_size: int
    patch_size: int | None = None

    def preprocess(self, image: Image.Image) -> tuple[np.ndarray, tuple[int, int, int, int]]:
        """Image RGB orientée → (tableau (3, S, S) float32, position de l'œuvre dans le carré)."""
        box = letterbox_box(*image.size, self.input_size)
        return to_normalized_array(letterbox(image, self.input_size)), box

    @abstractmethod
    def encode(self, batch: np.ndarray) -> EncodedBatch:
        """Encode un lot prétraité (N, 3, S, S) float32."""

    def runtime_stats(self) -> dict:
        """Mesures d'exécution à consigner dans le manifest (ex. VRAM maximale)."""
        return {}

    def describe(self) -> dict:
        """Ce qui est écrit dans le manifest du run."""
        return {
            "encoder": self.name,
            "dim": self.dim,
            "input_size": self.input_size,
            "patch_size": self.patch_size,
            "preprocess": "letterbox",
        }
