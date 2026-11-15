"""Crée des « paires connues » pour le banc d'essai : des variantes d'œuvres dont on
connaît l'original, imitant ce que l'historien de l'art rencontre réellement.

Types de variantes :
  gravure_inversee   noir et blanc contrasté + miroir (une gravure d'interprétation
                     inverse souvent la composition du tableau)
  reproduction_nb    vieille photographie : noir et blanc, flou léger, grain
  detail_recadre     recadrage d'environ 65 % de l'œuvre, légère rotation
  copie_alteree      couleurs décalées, petite taille, forte compression JPEG

Usage :
    python scripts/make_variants.py data/corpus/wikiart/metadata.csv data/corpus/variants --n 250

Produit <sortie>/images/... et <sortie>/metadata.csv (path, variant_of, variant_type).
"""

from __future__ import annotations

import argparse
import csv
import io
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from pixplot.imageio import open_image


def gravure_inversee(im: Image.Image, rng: random.Random) -> Image.Image:
    g = ImageOps.autocontrast(ImageOps.grayscale(im), cutoff=2)
    g = ImageEnhance.Contrast(g).enhance(1.6)
    return ImageOps.mirror(g).filter(ImageFilter.SHARPEN).convert("RGB")


def reproduction_nb(im: Image.Image, rng: random.Random) -> Image.Image:
    g = ImageOps.grayscale(im).filter(ImageFilter.GaussianBlur(1.2))
    arr = np.asarray(g, dtype=np.float32)
    arr += np.random.default_rng(rng.randrange(1 << 30)).normal(0, 10, arr.shape)
    g = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    return ImageOps.colorize(g, (30, 25, 20), (235, 225, 205))  # teinte sépia légère


def detail_recadre(im: Image.Image, rng: random.Random) -> Image.Image:
    w, h = im.size
    f = rng.uniform(0.6, 0.7)
    cw, ch = int(w * f), int(h * f)
    x, y = rng.randint(0, w - cw), rng.randint(0, h - ch)
    crop = im.crop((x, y, x + cw, y + ch))
    return crop.rotate(rng.uniform(-4, 4), resample=Image.Resampling.BICUBIC, expand=False, fillcolor=(255, 255, 255))


def copie_alteree(im: Image.Image, rng: random.Random) -> Image.Image:
    arr = np.asarray(im, dtype=np.float32)
    arr = arr * np.array([rng.uniform(0.8, 1.2) for _ in range(3)]) + rng.uniform(-20, 20)
    im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    im = ImageEnhance.Color(im).enhance(rng.uniform(0.6, 1.4))
    im.thumbnail((380, 380))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=25)
    return Image.open(io.BytesIO(buf.getvalue())).convert("RGB")


VARIANTS = {f.__name__: f for f in (gravure_inversee, reproduction_nb, detail_recadre, copie_alteree)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("metadata_csv", type=Path, help="CSV du corpus source (colonne path)")
    ap.add_argument("out", type=Path)
    ap.add_argument("--n", type=int, default=250, help="nombre d'œuvres originales")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    rng = random.Random(a.seed)
    base = a.metadata_csv.resolve().parent
    rows = list(csv.DictReader(open(a.metadata_csv, encoding="utf-8")))
    chosen = rng.sample(rows, min(a.n, len(rows)))
    out_rows = []
    for i, row in enumerate(chosen):
        original = (base / row["path"]).resolve()
        im = open_image(original, target=1024)
        im.thumbnail((1024, 1024))
        for name, fn in VARIANTS.items():
            target = a.out / "images" / name / f"{i:04d}.jpg"
            target.parent.mkdir(parents=True, exist_ok=True)
            fn(im, rng).save(target, "JPEG", quality=90)
            out_rows.append({"path": target.relative_to(a.out).as_posix(),
                             "variant_of": original.as_posix(), "variant_type": name})
    with open(a.out / "metadata.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["path", "variant_of", "variant_type"])
        w.writeheader()
        w.writerows(out_rows)
    print(f"{len(out_rows)} variantes de {len(chosen)} œuvres -> {a.out}")


if __name__ == "__main__":
    main()
