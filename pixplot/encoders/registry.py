"""Choisir un encodeur par son nom."""

from __future__ import annotations

from .base import Encoder

ENCODERS = (
    "dinov3_vitb16", "dinov3_vitl16", "dinov3_vits16",
    "dinov2_vitb14_reg", "dinov2_vitl14_reg", "dinov2_vits14_reg",
    "siglip2_so400m", "siglip2_base",
    "tipsv2_b14", "tipsv2_l14", "tipsv2_so400m14",
    "colorhist", "color_lab", "dinov3_vitb16_texture", "pe_spatial_b16",
    "sscd_disc_mixup", "sscd_disc_large", "depth_anything_v2_small",
    "depth_pro2_small", "depth_pro2_base", "depth_pro2_large",
    "pe_core_b16", "pe_core_l14", "pe_core_g14", "csd_vitl14",
    "vitpose_base", "vitpose_r18",
)


def get_encoder(name: str, **kwargs) -> Encoder:
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    if name == "colorhist":
        from .colorhist import ColorHistEncoder
        return ColorHistEncoder()
    if name == "color_lab":
        from .colorlab import ColorLabEncoder
        return ColorLabEncoder()
    if name.startswith("dinov3_") and name.endswith("_texture"):
        from .texture import DINOv3TextureEncoder
        return DINOv3TextureEncoder(arch=name, **kwargs)
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
    if name.startswith("tipsv2_"):
        from .tipsv2 import TIPSv2Encoder
        kwargs.pop("weights", None)
        kwargs.pop("repo", None)
        return TIPSv2Encoder(arch=name, **kwargs)
    if name.startswith("pe_core_"):
        from .pe_core import PECoreEncoder
        kwargs.pop("weights", None)
        kwargs.pop("repo", None)
        if kwargs.get("input_size") == 448 and name != "pe_core_g14":
            kwargs.pop("input_size")
        allowed = ("hf_model", "input_size", "device", "fp16", "vision_model", "text_model", "tokenizer")
        return PECoreEncoder(arch=name, **{k: v for k, v in kwargs.items() if k in allowed})
    if name.startswith("pe_spatial_"):
        from .pe_spatial import PESpatialEncoder
        return PESpatialEncoder(arch=name, **{k: v for k, v in kwargs.items() if k in ("input_size", "device", "fp16")})
    if name.startswith("sscd_"):
        from .sscd import SSCDEncoder
        if kwargs.get("input_size") == 448:  # 448 est la valeur par défaut de la CLI (DINOv3)
            kwargs.pop("input_size")
        allowed = ("weights", "cache_dir", "input_size", "device", "fp16")
        return SSCDEncoder(arch=name, **{k: v for k, v in kwargs.items() if k in allowed})
    if name.startswith("csd_"):
        from .csd import CSDEncoder
        kwargs.pop("repo", None)
        if kwargs.get("input_size") == 448:  # 448 est la valeur par défaut de la CLI (DINOv3)
            kwargs.pop("input_size")
        allowed = ("hf_model", "weights", "input_size", "device", "fp16", "model")
        return CSDEncoder(arch=name, **{k: v for k, v in kwargs.items() if k in allowed})
    if name.startswith("depth_anything_"):
        from .depth import DepthAnythingEncoder
        kwargs.pop("weights", None)
        kwargs.pop("repo", None)
        if kwargs.get("input_size") == 448:  # 448 est la valeur par défaut de la CLI (DINOv3)
            kwargs.pop("input_size")
        allowed = ("hf_model", "input_size", "grid", "device", "fp16", "model")
        return DepthAnythingEncoder(arch=name, **{k: v for k, v in kwargs.items() if k in allowed})
    if name.startswith("depth_pro2_"):
        from .depth_pro2 import DepthPro2Encoder
        kwargs.pop("weights", None)
        kwargs.pop("repo", None)
        if kwargs.get("input_size") == 448:  # 448 est la valeur par défaut de la CLI (DINOv3)
            kwargs.pop("input_size")
        allowed = ("hf_model", "input_size", "grid", "device", "fp16", "model")
        return DepthPro2Encoder(arch=name, **{k: v for k, v in kwargs.items() if k in allowed})
    if name.startswith("vitpose_"):
        from .posture import ViTPoseEncoder
        kwargs.pop("weights", None)
        kwargs.pop("repo", None)
        if kwargs.get("input_size") == 448:  # 448 est la valeur par défaut de la CLI (DINOv3)
            kwargs.pop("input_size")
        allowed = ("hf_model", "detector_model", "input_size", "det_threshold",
                   "max_figures", "device", "fp16", "det_module", "pose_module")
        return ViTPoseEncoder(arch=name, **{k: v for k, v in kwargs.items() if k in allowed})
    if name.startswith("dinov2_"):
        from .dinov2 import DINOv2Encoder
        kwargs.pop("weights", None)
        kwargs.pop("repo", None)
        return DINOv2Encoder(arch=name, **kwargs)
    raise ValueError(f"Encodeur inconnu : {name} (choix : {', '.join(ENCODERS)})")
