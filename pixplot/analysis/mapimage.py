"""Première carte : une grande image où chaque œuvre est posée à sa place UMAP.

C'est l'équivalent statique de la vue d'ensemble de PixPlot ; l'interface interactive
arrive à l'étape 4. Les numéros de groupe sont posés au centre de chaque groupe.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from ..catalog.ingest import thumb_path
from ..runs import Run

PALETTE = [(230, 159, 0), (86, 180, 233), (0, 158, 115), (240, 228, 66),
           (0, 114, 178), (213, 94, 0), (204, 121, 167), (170, 170, 170)]


def _font(size: int):
    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_map(analysis: Run, thumbs_dir: Path, out: Path, size: int = 4000, thumb: int = 56,
               labels: bool = True, background=(17, 17, 17)) -> Path:
    p = Path(analysis.path)
    ids = np.load(p / "ids.npy")
    coords = np.load(p / "coords.npy")
    clusters = np.load(p / "clusters.npy")
    margin = thumb
    xy = ((coords + 1) / 2 * (size - 2 * margin) + margin).astype(int)
    xy[:, 1] = size - xy[:, 1]  # l'axe y de l'image va vers le bas

    canvas = Image.new("RGB", (size, size), background)
    # Les œuvres les plus centrales de leur groupe sont posées en dernier (visibles au-dessus).
    for i in np.argsort(np.load(p / "atypicality.npy"))[::-1]:
        t = thumb_path(thumbs_dir, int(ids[i]), 64)
        if not t.exists():
            continue
        with Image.open(t) as im:
            im = im.convert("RGB")
            im.thumbnail((thumb, thumb))
            x, y = xy[i]
            canvas.paste(im, (x - im.width // 2, y - im.height // 2))

    if labels:
        draw = ImageDraw.Draw(canvas)
        font = _font(max(18, size // 120))
        summary = json.loads((p / "clusters.json").read_text(encoding="utf-8"))
        for entry in summary:
            members = clusters == entry["cluster"]
            cx, cy = np.median(xy[members], axis=0).astype(int)
            text = str(entry["cluster"] + 1)
            box = draw.textbbox((cx, cy), text, font=font, anchor="mm")
            pad = 6
            color = PALETTE[entry["cluster"] % len(PALETTE)]
            draw.rounded_rectangle((box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad),
                                   radius=8, fill=(0, 0, 0), outline=color, width=3)
            draw.text((cx, cy), text, font=font, fill=color, anchor="mm")

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, quality=88)
    return out
