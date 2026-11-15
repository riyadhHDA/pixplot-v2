"""Lecture robuste des images d'un corpus patrimonial.

Gère les cas fréquents dans les collections de musées : scans très grands, TIFF 16 bits,
transparence, orientation EXIF, formats variés.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

# Les scans de musée dépassent souvent la limite par défaut de Pillow (~89 Mpx).
Image.MAX_IMAGE_PIXELS = 500_000_000

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp", ".gif", ".jp2"}

_EXIF_ORIENTATION = 0x0112


def is_image_path(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def to_rgb(im: Image.Image, background: tuple[int, int, int] = (255, 255, 255)) -> Image.Image:
    """Convertit n'importe quel mode Pillow en RGB 8 bits."""
    if im.mode == "RGB":
        return im
    if im.mode in ("I;16", "I;16B", "I;16L", "I", "F"):
        arr = np.asarray(im, dtype=np.float32)
        lo, hi = np.percentile(arr, (0.5, 99.5))
        arr = np.clip((arr - lo) / max(hi - lo, 1e-6) * 255.0, 0, 255).astype(np.uint8)
        return Image.fromarray(arr, "L").convert("RGB")
    if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        canvas = Image.new("RGB", im.size, background)
        canvas.paste(im, mask=im.getchannel("A"))
        return canvas
    return im.convert("RGB")


def oriented_size(im: Image.Image) -> tuple[int, int]:
    """Taille réelle de l'œuvre une fois l'orientation EXIF appliquée, sans décoder l'image."""
    w, h = im.size
    try:
        orientation = im.getexif().get(_EXIF_ORIENTATION, 1)
    except Exception:
        orientation = 1
    return (h, w) if orientation in (5, 6, 7, 8) else (w, h)


def open_image(path: str | Path, target: int | None = None) -> Image.Image:
    """Ouvre une image en RGB, orientée correctement.

    ``target`` : taille utile maximale. Pour les JPEG, le décodage est alors fait
    directement à résolution réduite (beaucoup plus rapide sur les gros scans).
    """
    with Image.open(path) as im:
        if target:
            im.draft("RGB", (target, target))
        im = ImageOps.exif_transpose(im)  # renvoie une copie chargée
    return to_rgb(im)
