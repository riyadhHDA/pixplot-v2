"""Choisir un encodeur par son nom."""

from __future__ import annotations

from .base import Encoder

ENCODERS = ("dinov3_vits16", "dinov3_vitb16", "dinov3_vitl16", "colorhist")


def get_encoder(name: str, **kwargs) -> Encoder:
    if name == "colorhist":
        from .colorhist import ColorHistEncoder
        return ColorHistEncoder()
    if name.startswith("dinov3_"):
        from .dinov3 import DINOv3Encoder
        kwargs = {k: v for k, v in kwargs.items() if v is not None}
        if "weights" not in kwargs:
            kwargs["weights"] = f"weights/{name}.pth"
        return DINOv3Encoder(arch=name, **kwargs)
    raise ValueError(f"Encodeur inconnu : {name} (choix : {', '.join(ENCODERS)})")
