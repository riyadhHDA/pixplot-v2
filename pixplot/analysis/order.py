"""Ordre et désordre de la matière picturale sur tout un corpus : entropie de permutation H et
complexité statistique C de chaque œuvre (Sigaki, Perc et Ribeiro, *PNAS* 2018), calculées sur
la luminance des vignettes de 256 px, sans GPU (voir ``connoisseur.entropy_complexity``).

Sortie : ``ordre.npy`` (N, 2) dans le run d'analyse, aligné sur ``ids.npy`` (NaN pour une œuvre
sans vignette). Ce sont des mesures de la *reproduction* : la compression JPEG, la taille de la
vignette et l'état de la photographie les influencent. Elles ne disent rien de la qualité d'une
œuvre ; elles situent sa surface entre l'aplat régulier et le bruit.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

import numpy as np

FILE = "ordre.npy"


def _one(path: Path) -> tuple[float, float]:
    from PIL import Image

    from .connoisseur import entropy_complexity

    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail((256, 256), Image.Resampling.BILINEAR)
            arr = np.asarray(im, dtype=np.float32) / 255.0
    except Exception:  # vignette absente ou illisible
        return float("nan"), float("nan")
    lum = 0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]
    return entropy_complexity(lum)


def compute(analysis, settings, workers: int = 8, say: Callable[[str], None] = print) -> Path:
    """H et C de toutes les œuvres de l'analyse ; reprend ce qui manque si le fichier existe."""
    from ..catalog.ingest import thumb_path

    p = Path(analysis.path)
    ids = np.load(p / "ids.npy")
    out_path = p / FILE
    out = np.load(out_path) if out_path.exists() else np.full((len(ids), 2), np.nan, dtype=np.float32)
    todo = np.flatnonzero(np.isnan(out[:, 0]))
    say(f"  {len(todo)} œuvres à mesurer ({len(ids) - len(todo)} déjà faites)")
    paths = [thumb_path(settings.thumbs_dir, int(ids[r]), 256) for r in todo]
    with ThreadPoolExecutor(workers) as pool:
        for k, (r, hc) in enumerate(zip(todo, pool.map(_one, paths, chunksize=64))):
            out[r] = hc
            if k and k % 10_000 == 0:
                np.save(out_path, out)
                say(f"  {k}/{len(todo)}")
    np.save(out_path, out)
    return out_path


def load(analysis) -> np.ndarray | None:
    path = Path(analysis.path) / FILE
    return np.load(path) if path.exists() else None


def by_label(values: list[str], hc: np.ndarray, min_count: int = 200) -> list[dict]:
    """Médianes de H et C par étiquette (style, genre…), des plus ordonnées aux plus désordonnées."""
    rows = []
    vals = np.array(values, dtype=object)
    for v in sorted(set(values)):
        if not v or str(v).lower().startswith("unknown"):
            continue
        m = (vals == v) & ~np.isnan(hc[:, 0])
        if m.sum() < min_count:
            continue
        rows.append({"value": v, "n": int(m.sum()), "H": round(float(np.median(hc[m, 0])), 3),
                     "C": round(float(np.median(hc[m, 1])), 3)})
    return sorted(rows, key=lambda r: r["H"])


def summary_json(rows: list[dict]) -> str:
    return json.dumps(rows, ensure_ascii=False, indent=1)
