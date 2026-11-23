"""Planche d'illustration du regard « posture » : paires d'œuvres, squelette de la figure qui se
répond dessiné sur chacune, mention du miroir. Usage (depuis la racine du dépôt, PYTHONPATH=.) :
python scripts/planche_posture.py <sortie.jpg> "a|b|pose|Artiste A, date — Titre A|Artiste B, date — Titre B" …
(PLATE_LANG=en pour la version anglaise ; ne mettre que des œuvres du domaine public)."""
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from pixplot.catalog import db
from pixplot.catalog.ingest import thumb_path
from pixplot.catalog.metadata import get_metadata
from pixplot.encoders.posture import mirror_pose_vector

DATA = Path("data/wikiart81k")
RUN = DATA / "runs/features/vitpose_base_20261121-182701"
BG, PANEL, GOLD, TEXT, MUTED = (20, 20, 22), (30, 30, 34), (224, 176, 64), (236, 236, 236), (150, 150, 156)
# os (COCO 17) : tête, bras, tronc, jambes
LIMBS = [(5, 7), (7, 9), (6, 8), (8, 10), (5, 6), (11, 12), (5, 11), (6, 12), (11, 13), (13, 15), (12, 14), (14, 16),
         (0, 5), (0, 6)]


def font(name, size):
    for n in (name, "segoeui.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    return ImageFont.load_default()


ids = np.load(RUN / "ids.npy")
row = {int(i): r for r, i in enumerate(ids)}
VEC = np.load(RUN / "poses_vecs.npy", mmap_mode="r")
KPT = np.load(RUN / "poses_kpts.npy", mmap_mode="r")
CNT = np.load(RUN / "poses_count.npy", mmap_mode="r")
conn = db.connect(DATA / "catalog.sqlite")


def best_match(a, b):
    ra, rb = row[a], row[b]
    va = np.asarray(VEC[ra, :CNT[ra]], dtype=np.float32)
    vb = np.asarray(VEC[rb, :CNT[rb]], dtype=np.float32)
    best = (-2, 0, 0, False)
    for i, x in enumerate(va):
        for j, y in enumerate(vb):
            for mir in (False, True):
                s = float(x @ (mirror_pose_vector(y) if mir else y))
                if s > best[0]:
                    best = (s, i, j, mir)
    return best


def draw(aid, fig, w_box, h_box):
    im = Image.open(thumb_path(DATA / "thumbs", aid, 1024)).convert("RGB")
    W, H = im.size
    sc = min(w_box / W, h_box / H)
    im = im.resize((round(W * sc), round(H * sc)), Image.LANCZOS)
    kp = np.asarray(KPT[row[aid], fig], dtype=np.float32)
    m = max(W, H)
    fx, fy = W / m, H / m  # part du carré occupée par l'œuvre
    px = (kp[:, 0] - (1 - fx) / 2) / fx * im.width
    py = (kp[:, 1] - (1 - fy) / 2) / fy * im.height
    ok = kp[:, 2] >= 0.30
    d = ImageDraw.Draw(im, "RGBA")
    lw = max(3, im.width // 140)
    for p, q in LIMBS:
        if ok[p] and ok[q]:
            d.line([(px[p], py[p]), (px[q], py[q])], fill=(0, 0, 0, 150), width=lw + 3)
            d.line([(px[p], py[p]), (px[q], py[q])], fill=GOLD + (235,), width=lw)
    r = lw + 1
    for k in range(17):
        if ok[k]:
            d.ellipse([px[k] - r, py[k] - r, px[k] + r, py[k] + r], fill=(255, 245, 220, 255), outline=(0, 0, 0, 160))
    return im


def label(meta):
    art = (meta.get("artist") or "?").replace("-", " ").title()
    t = meta.get("title") or ""
    d = meta.get("date") or ""
    return art, (t[:1].upper() + t[1:]) if t else "", d


EN = os.environ.get("PLATE_LANG") == "en"
T = {
    "title": "PixPlot v2 · the “posture” regard" if EN else "PixPlot v2 · le regard « posture »",
    "sub": ("The same gesture across centuries, media and artists — found without any label, by comparing "
            "the skeletons of the figures, mirror images included.") if EN else
           ("Le même geste, d'un siècle, d'un médium et d'un artiste à l'autre — retrouvé sans aucune étiquette, "
            "en comparant les squelettes des figures, y compris en miroir."),
    "sim": "pose similarity" if EN else "ressemblance de pose",
    "mirror": "mirrored" if EN else "en miroir",
    "foot": ("Public-domain works (WikiArt). RT-DETRv2 detector and ViTPose skeletons (Apache 2.0). "
             "A similar pose is a lead, not proof that one artist saw the other.") if EN else
            ("Œuvres du domaine public (WikiArt). Détecteur RT-DETRv2 et squelettes ViTPose (Apache 2.0). "
             "Une pose semblable est une piste, pas la preuve qu'un artiste a vu l'autre."),
}


def main():
    out = Path(sys.argv[1])
    specs = [s.split("|") for s in sys.argv[2:]]
    pairs = [(int(a), int(b), pose) for a, b, pose, *_ in specs]
    names = {}
    for a, b, pose, *lab in specs:
        if len(lab) == 2:
            names[int(a)], names[int(b)] = lab
    meta = get_metadata(conn, [x for a, b, _ in pairs for x in (a, b)])
    Wt, IMG_H, IMG_W, GAP, M = 1600, 430, 600, 26, 40
    head, row_h = 150, IMG_H + 134
    canvas = Image.new("RGB", (Wt, head + row_h * len(pairs) + 90), BG)
    d = ImageDraw.Draw(canvas)
    fT, fS, fP, fA, fN, fSm = (font("georgiab.ttf", 46), font("segoeui.ttf", 20), font("georgiai.ttf", 26),
                               font("segoeuib.ttf", 20), font("segoeui.ttf", 18), font("segoeui.ttf", 17))
    d.text((M, 34), T["title"], font=fT, fill=TEXT)
    d.text((M, 98), T["sub"], font=fS, fill=MUTED)
    y = head
    for a, b, pose in pairs:
        s, i, j, mir = best_match(a, b)
        d.rounded_rectangle([M - 14, y - 10, Wt - M + 14, y + row_h - 24], radius=14, fill=PANEL)
        d.text((M, y), pose, font=fP, fill=GOLD)
        badge = f"{T['sim']} {s:.2f}" + (f"  ·  {T['mirror']}" if mir else "")
        if not EN:
            badge = badge.replace(".", ",")
        bw = d.textlength(badge, font=fN)
        d.text((Wt - M - bw, y + 6), badge, font=fN, fill=TEXT)
        ia, ib = draw(a, i, IMG_W, IMG_H), draw(b, j, IMG_W, IMG_H)
        cx = Wt // 2
        xa = cx - GAP // 2 - ia.width
        xb = cx + GAP // 2
        yi = y + 44 + (IMG_H - max(ia.height, ib.height)) // 2
        canvas.paste(ia, (xa, y + 44 + (IMG_H - ia.height) // 2))
        canvas.paste(ib, (xb, y + 44 + (IMG_H - ib.height) // 2))
        for x0, w, aid in ((xa, ia.width, a), (xb, ib.width, b)):
            art, title, date = label(meta.get(aid, {}))
            if aid in names:
                line1, title = names[aid].split(" — ", 1)
            else:
                line1 = f"{art}" + (f", {date}" if date else "")
            d.text((x0, y + 44 + IMG_H + 10), line1, font=fA, fill=TEXT)
            d.text((x0, y + 44 + IMG_H + 36), title[:60], font=fN, fill=MUTED)
        y += row_h
    foot = T["foot"]
    d.text((M, y + 20), foot, font=fSm, fill=MUTED)
    canvas.save(out, quality=90)
    print(out, canvas.size)


main()
