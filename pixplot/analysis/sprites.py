"""Planches de vignettes (« atlas de textures ») pour afficher toutes les œuvres à la fois.

Au lieu de télécharger une vignette par œuvre (lent, et source de scintillement quand les
vignettes entrent et sortent de l'écran), on assemble toutes les vignettes d'une analyse
dans quelques grandes images de 4096 × 4096 px. Le navigateur les charge une fois sur le
GPU, et toutes les œuvres restent affichées en permanence. C'était l'idée du PixPlot
d'origine (planches de 2048 px) ; ici, taille de case adaptée à la taille du corpus.

Fichiers, dans ``<analyse>/sprites/`` (recalculés seulement s'ils manquent) :
    sheet-<n>.jpg     planches (fond noir, chaque vignette centrée dans sa case)
    sprites.json      taille de case, nombre de planches, et pour chaque ligne de l'analyse :
                      planche, x, y, largeur, hauteur de la vignette dans la planche
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from ..catalog.ingest import thumb_path
from ..runs import Run

SHEET = 4096


def cell_size(n: int) -> int:
    """Taille d'une case : assez fine pour tenir en mémoire GPU, assez grande pour bien voir.

    64 px jusqu'à 30 000 œuvres (≈ 0,5 Go de texture), 32 px au-delà (500 000 œuvres ≈ 2 Go
    sur 16 Go de VRAM). Les détails s'affichent de toute façon en haute définition au zoom.
    """
    return 64 if n <= 30_000 else 32


def build_sprites(analysis: Run, thumbs_dir: Path, force: bool = False) -> Path:
    out = Path(analysis.path) / "sprites"
    meta_path = out / "sprites.json"
    if meta_path.exists() and not force:
        return meta_path
    ids = np.load(Path(analysis.path) / "ids.npy")
    n = len(ids)
    cell = cell_size(n)
    per_row = SHEET // cell
    per_sheet = per_row * per_row
    sheets = (n + per_sheet - 1) // per_sheet
    out.mkdir(parents=True, exist_ok=True)

    sheet_of = np.zeros(n, dtype=np.int32)
    xs = np.zeros(n, dtype=np.int32)
    ys = np.zeros(n, dtype=np.int32)
    ws = np.zeros(n, dtype=np.int32)
    hs = np.zeros(n, dtype=np.int32)
    src_size = 64 if cell <= 64 else 256

    for s in range(sheets):
        start, stop = s * per_sheet, min(n, (s + 1) * per_sheet)
        rows_here = (stop - start + per_row - 1) // per_row
        canvas = Image.new("RGB", (SHEET, max(cell, rows_here * cell)), (0, 0, 0))
        for k, r in enumerate(range(start, stop)):
            cx, cy = (k % per_row) * cell, (k // per_row) * cell
            t = thumb_path(thumbs_dir, int(ids[r]), src_size)
            try:
                with Image.open(t) as im:
                    im = im.convert("RGB")
                    im.thumbnail((cell, cell), Image.Resampling.LANCZOS)
            except OSError:
                im = Image.new("RGB", (cell // 2, cell // 2), (60, 60, 60))
            ox, oy = cx + (cell - im.width) // 2, cy + (cell - im.height) // 2
            canvas.paste(im, (ox, oy))
            sheet_of[r], xs[r], ys[r], ws[r], hs[r] = s, ox, oy, im.width, im.height
        canvas.save(out / f"sheet-{s}.jpg", quality=88, optimize=True)

    meta = {"cell": cell, "sheet": SHEET, "sheets": sheets, "count": n,
            "atlas": sheet_of.tolist(), "x": xs.tolist(), "y": ys.tolist(),
            "w": ws.tolist(), "h": hs.tolist()}
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    return meta_path
