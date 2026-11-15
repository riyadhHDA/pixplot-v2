"""Choisir un encodeur par son nom."""

from __future__ import annotations

from .base import Encoder

ENCODERS = (
    "dinov3_vitb16", "dinov3_vitl16", "dinov3_vits16",
    "dinov2_vitb14_reg", "dinov2_vitl14_reg", "dinov2_vits14_reg",
    "siglip2_so400m", "siglip2_base",
    "colorhist",
)


def get_encoder(name: str, **kwargs) -> Encoder:
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    if name == "colorhist":
        from .colorhist import ColorHistEncoder
        return ColorHistEncoder()
    if name.startswith("dinov3_"):
        from .dinov3 import DINOv3Encoder
        return DINOv3Encoder(arch=name, **kwargs)
    if name.startswith("siglip2_"):
        from .siglip2 import SigLIP2Encoder
        kwargs.pop("weights", None)
        kwargs.pop("repo", None)
        if kwargs.get("input_size") == 448:  # 448 est la valeur par défaut de la CLI (DINOv3)
            kwargs.pop("input_size")
        return SigLIP2Encoder(arch=name, **kwargs)
    if name.startswith("dinov2_"):
        from .dinov2 import DINOv2Encoder
        kwargs.pop("weights", None)
        kwargs.pop("repo", None)
        return DINOv2Encoder(arch=name, **kwargs)
    raise ValueError(f"Encodeur inconnu : {name} (choix : {', '.join(ENCODERS)})")
