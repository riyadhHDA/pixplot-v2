"""Encodeur DINOv2 « with registers » (Meta, Apache 2.0, sans demande d'accès).

Sert à démarrer tout de suite en attendant la validation de DINOv3, puis de point de
comparaison : chaque run étant versionné, on compare les deux sur le même corpus.
Patchs de 14 px : la résolution doit être un multiple de 14 (448 convient).
"""

from __future__ import annotations

from .hf_vit import HFViTEncoder

ARCH = {
    "dinov2_vits14_reg": ("facebook/dinov2-with-registers-small", 384),
    "dinov2_vitb14_reg": ("facebook/dinov2-with-registers-base", 768),
    "dinov2_vitl14_reg": ("facebook/dinov2-with-registers-large", 1024),
}


class DINOv2Encoder(HFViTEncoder):
    def __init__(self, arch: str = "dinov2_vitb14_reg", hf_model: str | None = None,
                 input_size: int = 448, device: str | None = None, fp16: bool = True):
        if arch not in ARCH:
            raise ValueError(f"Architecture inconnue : {arch} (choix : {', '.join(ARCH)})")
        default_id, dim = ARCH[arch]
        super().__init__(arch, hf_model or default_id, dim, 14,
                         input_size=input_size, device=device, fp16=fp16)
