"""Banc d'essai d'occultation du bouton « Pourquoi ? » (correspondances mutuelles DINOv3).

Question critique (Wasielewski, *Computational Formalism*, 2023) : les 4 zones mises en avant par
le bouton « Pourquoi ? » (``correspondences.py``) sont-elles réellement **celles qui portent la
ressemblance globale** calculée par DINOv3, ou seulement une illustration plausible a posteriori ?

Protocole :
- Paires : paires validées (``bench/wikiart81k_pairs.csv`` ou ``pairs.csv``), plus autant de paires
  témoins « voisines proches » (première voisine en forme d'une œuvre tirée au sort, graine fixe).
- Vérification préalable : sans occultation, on vérifie que le réencodage reproduit les cosinus du
  run de référence à moins de 0,01 près (même prétraitement letterbox).
- Occultation, sur les deux images à la fois (``both``) puis sur une seule (``one``, image A) :
  - (a) ``why``    : les 4 premières zones du « Pourquoi ? » ;
  - (b) ``random`` : 4 zones tirées au hasard parmi les cases valides de l'œuvre (hors bandes de
    letterbox), moyenne sur 10 tirages ;
  - (c) ``center`` : les 4 cases centrales de la grille 4 × 4 (cases 5, 6, 9, 10).
- Deux remplissages : couleur moyenne de l'œuvre (``mean``, hors bandes) et flou gaussien fort
  (``blur``), pour vérifier que la conclusion ne dépend pas du mode de masquage.
- Mesure : chute du cosinus = cosinus d'origine − cosinus après occultation.
- Statistiques : médianes et moyennes avec IC 95 % par bootstrap sur les paires, écarts appariés
  (a − b) et (a − c) avec IC et p bilatéral. Critère fixé d'avance : réussi si la chute médiane
  de (a) dépasse celle de (b) d'un facteur >= 3 et que l'IC 95 % de (a − b) exclut zéro.

Ne modifie pas le calcul du « Pourquoi ? » : on mesure l'existant.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..catalog import db
from ..catalog.metadata import get_metadata
from ..encoders.base import Encoder, letterbox, letterbox_box, to_normalized_array
from ..features.extract import OK
from ..features.regions import DEFAULT_GRIDS
from ..imageio import open_image
from ..index.regions import cell_boxes, patches_per_side, square_to_image
from ..runs import Run
from .correspondences import GRID, cells_of, correspondences, load_or_compute_cell_means
from .pairbench import Pair, TYPES, load_pairs

CENTER_CELLS = (5, 6, 9, 10)
FILL_MODES = ("mean", "blur")
PALETTE_BOXES = (
    (230, 57, 70),    # 1 : rouge
    (42, 157, 143),   # 2 : sarcelle
    (244, 162, 97),   # 3 : orange
    (76, 201, 240),   # 4 : bleu clair
)


# ------------------------------------------------------------------ préparation des images et masques
@dataclass
class PreparedImage:
    artwork_id: int
    canvas: np.ndarray                 # (S, S, 3) uint8, image mise au carré (letterbox)
    box: tuple[int, int, int, int]     # (left, top, rw, rh) de l'œuvre dans le carré
    mean_rgb: np.ndarray               # (3,) uint8, couleur moyenne de l'œuvre seule
    blurred: np.ndarray | None = None  # (rh, rw, 3) uint8, flou fort calculé à la demande


def prepare_image(path: str | Path, input_size: int, artwork_id: int = 0) -> PreparedImage:
    """Charge l'image avec exactement le même prétraitement que ``extract.py`` (open_image + letterbox)."""
    img = open_image(path, target=input_size)
    box = letterbox_box(*img.size, input_size)
    canvas = np.asarray(letterbox(img, input_size), dtype=np.uint8)
    left, top, rw, rh = box
    art = canvas[top:top + rh, left:left + rw]
    mean_rgb = np.round(art.mean(axis=(0, 1))).astype(np.uint8)
    return PreparedImage(artwork_id=artwork_id, canvas=canvas, box=box, mean_rgb=mean_rgb)


def _ensure_blurred(prep: PreparedImage, radius: int) -> np.ndarray:
    if prep.blurred is None:
        left, top, rw, rh = prep.box
        art = Image.fromarray(prep.canvas[top:top + rh, left:left + rw], mode="RGB")
        prep.blurred = np.asarray(art.filter(ImageFilter.GaussianBlur(radius=radius)), dtype=np.uint8)
    return prep.blurred


def cell_pixel_rect(
    sq_box: tuple[float, float, float, float],
    content_box: tuple[int, int, int, int],
    size: int,
) -> tuple[int, int, int, int] | None:
    """Rectangle pixel ``(x0, y0, x1, y1)`` d'une case 4 × 4 dans le carré, rogné à l'œuvre."""
    left, top, rw, rh = content_box
    sx0, sy0, sx1, sy1 = sq_box
    x0 = max(left, int(round(sx0 * size)))
    y0 = max(top, int(round(sy0 * size)))
    x1 = min(left + rw, int(round(sx1 * size)))
    y1 = min(top + rh, int(round(sy1 * size)))
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def mask_canvas(
    prep: PreparedImage,
    cells: list[int] | tuple[int, ...],
    sq_boxes: list[tuple[float, float, float, float]],
    fill: str = "mean",
    blur_radius: int | None = None,
) -> tuple[np.ndarray, float]:
    """Applique une occultation sur les cases données, sans toucher aux bandes du letterbox.

    Renvoie ``(tableau_normalisé (3, S, S) float32, fraction_surface_œuvre_occultée)``.
    """
    size = prep.canvas.shape[0]
    left, top, rw, rh = prep.box
    out = prep.canvas.copy()
    mask_px = np.zeros((rh, rw), dtype=bool)
    blurred = None
    if fill == "blur":
        rad = blur_radius if blur_radius is not None else max(16, size // 14)
        blurred = _ensure_blurred(prep, rad)
    elif fill != "mean":
        raise ValueError(f"Mode de remplissage inconnu : {fill} (attendu : mean ou blur)")

    for c in cells:
        rect = cell_pixel_rect(sq_boxes[c], prep.box, size)
        if rect is None:
            continue
        x0, y0, x1, y1 = rect
        if fill == "mean":
            out[y0:y1, x0:x1] = prep.mean_rgb
        else:
            out[y0:y1, x0:x1] = blurred[y0 - top:y1 - top, x0 - left:x1 - left]
        mask_px[y0 - top:y1 - top, x0 - left:x1 - left] = True

    area = float(mask_px.sum()) / max(rw * rh, 1)
    arr = to_normalized_array(Image.fromarray(out, mode="RGB"))
    return arr, area


# ------------------------------------------------------------------ paires et cases valides
def valid_cells_for(
    regions: np.ndarray,
    size: tuple[int, int],
    grids: tuple[int, ...] = DEFAULT_GRIDS,
    patches: int | None = None,
) -> list[int]:
    """Indices (0..15) des cases 4 × 4 qui recouvrent l'œuvre (même règle que ``correspondences.match``)."""
    sq_boxes = [b for _, b in cell_boxes((GRID,), patches)]
    cvecs = cells_of(regions, grids)
    boxes = [square_to_image(b, *size) for b in sq_boxes]
    return [i for i, (bx, v) in enumerate(zip(boxes, cvecs))
            if bx is not None and float(np.linalg.norm(v)) > 1e-6]


def center_cells_for(valid_cells: list[int], sq_boxes: list[tuple[float, float, float, float]], k: int = 4) -> list[int]:
    """Les ``k`` cases centrales (5, 6, 9, 10 sur une grille 4 × 4), ou les plus proches du centre."""
    if k == 4 and all(c in valid_cells for c in CENTER_CELLS):
        return list(CENTER_CELLS)
    scored = []
    for c in valid_cells:
        x0, y0, x1, y1 = sq_boxes[c]
        cx, cy = 0.5 * (x0 + x1), 0.5 * (y0 + y1)
        scored.append(((cx - 0.5) ** 2 + (cy - 0.5) ** 2, c))
    scored.sort()
    return [c for _, c in scored[:k]]


def sample_neighbor_pairs(
    ids: np.ndarray,
    X: np.ndarray,
    n: int,
    seed: int = 0,
    exclude: set[tuple[int, int]] | None = None,
) -> list[Pair]:
    """Tire ``n`` œuvres au sort (graine fixe) et associe chacune à sa 1ʳᵉ voisine exacte dans ``X``.

    ``X`` : vecteurs globaux normalisés L2 (N, D) float32 alignés sur ``ids``.
    """
    if n <= 0 or len(ids) < 2:
        return []
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(ids))
    seen: set[tuple[int, int]] = set(exclude or ())
    out: list[Pair] = []
    pos = 0
    chunk = min(max(n * 2, 64), len(ids))
    while len(out) < n and pos < len(ids):
        batch = order[pos:pos + chunk]
        pos += len(batch)
        sim = X[batch] @ X.T
        sim[np.arange(len(batch)), batch] = -np.inf
        best = sim.argmax(axis=1)
        for row_a, row_b in zip(batch.tolist(), best.tolist()):
            a, b = int(ids[row_a]), int(ids[row_b])
            key = (min(a, b), max(a, b))
            if a == b or key in seen:
                continue
            seen.add(key)
            out.append(Pair(a=a, b=b, type="voisine_proche", origin="témoin", status="validée",
                            source=f"1re voisine forme (graine {seed})"))
            if len(out) >= n:
                break
    return out


# ------------------------------------------------------------------ encodage par lots
def _encode_arrays(encoder: Encoder, arrays: list[np.ndarray], batch_size: int = 32) -> np.ndarray:
    if not arrays:
        return np.empty((0, encoder.dim), dtype=np.float32)
    chunks = []
    for s in range(0, len(arrays), batch_size):
        batch = np.stack(arrays[s:s + batch_size]).astype(np.float32, copy=False)
        out = encoder.encode(batch)
        v = np.asarray(out.global_vectors, dtype=np.float32)
        v /= np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-12)
        chunks.append(v)
    return np.concatenate(chunks, axis=0)


# ------------------------------------------------------------------ statistiques bootstrap
def _cond_stats(vals: np.ndarray, idx: np.ndarray, lo_q: float, hi_q: float, areas: np.ndarray | None = None) -> dict:
    boot = vals[idx]
    med_b = np.median(boot, axis=1)
    mean_b = boot.mean(axis=1)
    out = {
        "median": round(float(np.median(vals)), 6),
        "median_ci": [round(float(np.percentile(med_b, lo_q)), 6), round(float(np.percentile(med_b, hi_q)), 6)],
        "mean": round(float(vals.mean()), 6),
        "mean_ci": [round(float(np.percentile(mean_b, lo_q)), 6), round(float(np.percentile(mean_b, hi_q)), 6)],
    }
    if areas is not None and len(areas):
        out["area_mean"] = round(float(areas.mean()), 4)
        out["area_median"] = round(float(np.median(areas)), 4)
    return out


def _paired_stats(a: np.ndarray, b: np.ndarray, idx: np.ndarray, lo_q: float, hi_q: float) -> dict:
    d = a - b
    boot_d = d[idx]
    mean_b = boot_d.mean(axis=1)
    med_b = np.median(boot_d, axis=1)
    p_mean = float(min(1.0, 2.0 * min((mean_b <= 0).mean(), (mean_b >= 0).mean())))
    p_med = float(min(1.0, 2.0 * min((med_b <= 0).mean(), (med_b >= 0).mean())))

    med_a, med_b_val = float(np.median(a)), float(np.median(b))
    mean_a, mean_b_val = float(a.mean()), float(b.mean())
    ratio_med = (med_a / med_b_val) if med_b_val > 1e-12 else None
    ratio_mean = (mean_a / mean_b_val) if mean_b_val > 1e-12 else None

    ba_med = np.median(a[idx], axis=1)
    bb_med = np.median(b[idx], axis=1)
    valid_r = bb_med > 1e-12
    ratio_med_ci = (
        [round(float(np.percentile(ba_med[valid_r] / bb_med[valid_r], lo_q)), 4),
         round(float(np.percentile(ba_med[valid_r] / bb_med[valid_r], hi_q)), 4)]
        if valid_r.mean() >= 0.5 else None
    )
    return {
        "mean_diff": round(float(d.mean()), 6),
        "mean_ci": [round(float(np.percentile(mean_b, lo_q)), 6), round(float(np.percentile(mean_b, hi_q)), 6)],
        "p_mean": round(p_mean, 4),
        "median_diff": round(float(np.median(d)), 6),
        "median_ci": [round(float(np.percentile(med_b, lo_q)), 6), round(float(np.percentile(med_b, hi_q)), 6)],
        "p_median": round(p_med, 4),
        "share_pos": round(float((d > 0).mean()), 4),
        "ratio_median": round(ratio_med, 4) if ratio_med is not None else None,
        "ratio_median_ci": ratio_med_ci,
        "ratio_mean": round(ratio_mean, 4) if ratio_mean is not None else None,
    }


def summarize_records(
    records: list[dict],
    mode: str,
    n_boot: int = 2000,
    seed: int = 0,
    level: float = 0.95,
) -> dict:
    """Statistiques bootstrap sur un ensemble de paires pour un mode d'occultation (``both`` ou ``one``)."""
    n = len(records)
    if n == 0:
        return {"n_pairs": 0}
    rng = np.random.default_rng(seed)
    lo_q, hi_q = (1.0 - level) / 2.0 * 100.0, (1.0 + level) / 2.0 * 100.0
    idx = rng.integers(n, size=(n_boot, n))

    da = np.array([r[mode]["drop_a"] for r in records], dtype=np.float64)
    db = np.array([r[mode]["drop_b"] for r in records], dtype=np.float64)
    dc = np.array([r[mode]["drop_c"] for r in records], dtype=np.float64)
    cos0 = np.array([r["cos_orig"] for r in records], dtype=np.float64)

    area_key = "area_both" if mode == "both" else "area_a"
    aa = np.array([r["areas"]["a"][area_key] for r in records], dtype=np.float64)
    ab = np.array([r["areas"]["b"][area_key] for r in records], dtype=np.float64)
    ac = np.array([r["areas"]["c"][area_key] for r in records], dtype=np.float64)

    p_ab = _paired_stats(da, db, idx, lo_q, hi_q)
    p_ac = _paired_stats(da, dc, idx, lo_q, hi_q)

    ci_ab_excl_zero = bool(p_ab["mean_ci"][0] > 0.0 and p_ab["median_ci"][0] > 0.0)
    ci_ab_mean_excl = bool(p_ab["mean_ci"][0] > 0.0)
    ci_ab_med_excl = bool(p_ab["median_ci"][0] > 0.0)
    ratio_ok = bool(p_ab["ratio_median"] is not None and p_ab["ratio_median"] >= 3.0)
    criterion_passed = bool(ratio_ok and ci_ab_med_excl)

    return {
        "n_pairs": n,
        "cos_orig_median": round(float(np.median(cos0)), 4),
        "cos_orig_mean": round(float(cos0.mean()), 4),
        "a_why": _cond_stats(da, idx, lo_q, hi_q, aa),
        "b_random": _cond_stats(db, idx, lo_q, hi_q, ab),
        "c_center": _cond_stats(dc, idx, lo_q, hi_q, ac),
        "diff_a_minus_b": p_ab,
        "diff_a_minus_c": p_ac,
        "criterion": {
            "rule": "chute médiane (a) / (b) >= 3 et IC 95 % de (a − b) exclut zéro",
            "ratio_median": p_ab["ratio_median"],
            "ratio_ge_3": ratio_ok,
            "ci_median_excludes_zero": ci_ab_med_excl,
            "ci_mean_excludes_zero": ci_ab_mean_excl,
            "ci_both_exclude_zero": ci_ab_excl_zero,
            "passed": criterion_passed,
        },
    }


def aggregate_fill(records: list[dict], n_boot: int = 2000, seed: int = 0, min_type_n: int = 10) -> dict:
    """Agrège les résultats d'un mode de remplissage par groupe (validées, voisines) et par type."""
    by_group: dict[str, list[dict]] = defaultdict(list)
    by_type: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_group[r["group"]].append(r)
        if r["group"] == "validees":
            by_type[r["type"]].append(r)

    out: dict = {"groups": {}, "by_type": {}, "by_type_counts": {t: len(v) for t, v in sorted(by_type.items())}}
    for grp, recs in sorted(by_group.items()):
        out["groups"][grp] = {
            "both": summarize_records(recs, "both", n_boot=n_boot, seed=seed),
            "one": summarize_records(recs, "one", n_boot=n_boot, seed=seed + 1),
        }
    for t, recs in sorted(by_type.items()):
        if len(recs) >= min_type_n:
            out["by_type"][t] = {
                "label": TYPES.get(t, (t,))[0],
                "both": summarize_records(recs, "both", n_boot=n_boot, seed=seed),
                "one": summarize_records(recs, "one", n_boot=n_boot, seed=seed + 1),
            }
    return out


# ------------------------------------------------------------------ planche visuelle de 6 paires
def select_sheet_pairs(records: list[dict], n_top: int = 3, n_bottom: int = 3) -> tuple[list[dict], list[dict]]:
    """Choisit 3 paires validées où (a) chute beaucoup et 3 où (a) ne chute pas plus que le hasard."""
    val = [r for r in records if r["group"] == "validees"]
    if not val:
        val = list(records)

    def pick_diverse(candidates: list[dict], limit: int, used_artworks: set[int]) -> list[dict]:
        chosen: list[dict] = []
        chosen_keys: set[tuple[int, int]] = set()
        for pass_idx in range(2):
            for r in candidates:
                key = (r["a"], r["b"])
                if key in chosen_keys:
                    continue
                if pass_idx == 0 and (r["a"] in used_artworks or r["b"] in used_artworks):
                    continue
                chosen.append(r)
                chosen_keys.add(key)
                used_artworks.update((r["a"], r["b"]))
                if len(chosen) >= limit:
                    return chosen
        return chosen

    used: set[int] = set()
    high_cands = sorted(
        val,
        key=lambda r: (r["both"]["drop_a"], r["both"]["drop_a"] - r["both"]["drop_b"]),
        reverse=True,
    )
    top = pick_diverse(high_cands, n_top, used)

    not_better = [r for r in val if r["both"]["drop_a"] <= r["both"]["drop_b"]]
    if len(not_better) >= n_bottom:
        low_cands = sorted(not_better, key=lambda r: (r["both"]["drop_a"] - r["both"]["drop_b"], -r["cos_orig"]))
    else:
        low_cands = sorted(val, key=lambda r: (r["both"]["drop_a"] - r["both"]["drop_b"], r["both"]["drop_a"]))
    bottom = pick_diverse([r for r in low_cands if (r["a"], r["b"]) not in {(x["a"], x["b"]) for x in top}], n_bottom, used)
    return top, bottom


def _draw_boxed_artwork(
    path: str | Path,
    matches: list[dict],
    side: str,
    max_w: int = 360,
    max_h: int = 290,
) -> Image.Image:
    im = open_image(path, target=max(max_w, max_h) * 2)
    scale = min(max_w / max(im.width, 1), max_h / max(im.height, 1), 1.0)
    nw, nh = max(1, round(im.width * scale)), max(1, round(im.height * scale))
    im = im.resize((nw, nh), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(im)
    font = ImageFont.load_default()
    box_key = "box_a" if side == "a" else "box_b"
    for idx, m in enumerate(matches[:4]):
        bx = m.get(box_key)
        if not bx:
            continue
        x0, y0, x1, y1 = int(round(bx[0] * nw)), int(round(bx[1] * nh)), int(round(bx[2] * nw)), int(round(bx[3] * nh))
        x1 = min(nw - 1, max(x0 + 2, x1))
        y1 = min(nh - 1, max(y0 + 2, y1))
        col = PALETTE_BOXES[idx % len(PALETTE_BOXES)]
        # double contour (noir + couleur) pour rester lisible sur fond clair ou sombre
        draw.rectangle([max(0, x0 - 1), max(0, y0 - 1), min(nw - 1, x1 + 1), min(nh - 1, y1 + 1)], outline=(0, 0, 0), width=4)
        draw.rectangle([x0, y0, x1, y1], outline=col, width=3)
        badge = [x0 + 2, y0 + 2, min(nw - 1, x0 + 20), min(nh - 1, y0 + 18)]
        draw.rectangle(badge, fill=col)
        draw.text((x0 + 7, y0 + 4), str(idx + 1), fill=(255, 255, 255), font=font)
    return im


def render_contact_sheet(
    top: list[dict],
    bottom: list[dict],
    artworks: dict[int, dict],
    meta: dict[int, dict],
    out_path: Path,
) -> Path:
    """Dessine une planche de 6 paires (3 fortes chutes, 3 pas mieux que le hasard) avec les 4 zones."""
    rows_spec = [(True, r) for r in top] + [(False, r) for r in bottom]
    if not rows_spec:
        raise ValueError("Aucune paire à dessiner pour la planche")

    pad = 16
    img_w, img_h = 360, 280
    hdr_h = 46
    row_h = hdr_h + img_h + pad
    title_h = 44
    W = pad * 3 + img_w * 2
    H = title_h + len(rows_spec) * row_h + pad

    sheet = Image.new("RGB", (W, H), (20, 20, 22))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    draw.text(
        (pad, 14),
        "PixPlot whytest — 3 fortes chutes de (a) en haut, 3 paires ou (a) <= hasard (b) en bas  [remplissage : moyenne, 2 images]",
        fill=(235, 235, 235),
        font=font,
    )

    def short_label(aid: int) -> str:
        m = meta.get(aid) or {}
        bits = [m.get(k) for k in ("artist", "title", "style", "genre")
                if m.get(k) and not str(m.get(k)).lower().startswith("unknown")]
        txt = " · ".join(bits[:2]) if bits else Path(artworks[aid]["path"]).name
        return txt[:48]

    y = title_h
    for is_top, r in rows_spec:
        tag = "FORTE CHUTE" if is_top else "PAS MIEUX QUE HASARD"
        tag_col = (110, 220, 140) if is_top else (240, 120, 110)
        b_res = r["both"]
        diff = b_res["drop_a"] - b_res["drop_b"]
        line1 = (f"[{tag}]  {r['type']}  |  #{r['a']} <-> #{r['b']}  |  "
                 f"cos={r['cos_orig']:.3f}  d(a)={b_res['drop_a']:+.3f}  "
                 f"d(b)={b_res['drop_b']:+.3f}  d(c)={b_res['drop_c']:+.3f}  (a-b)={diff:+.3f}")
        line2 = f"A (#{r['a']}): {short_label(r['a'])}    ||    B (#{r['b']}): {short_label(r['b'])}"
        draw.rectangle([pad, y, W - pad, y + hdr_h - 4], fill=(34, 34, 38))
        draw.text((pad + 8, y + 6), line1, fill=tag_col, font=font)
        draw.text((pad + 8, y + 24), line2, fill=(210, 210, 215), font=font)

        im_a = _draw_boxed_artwork(artworks[r["a"]]["path"], r["matches"], "a", img_w, img_h)
        im_b = _draw_boxed_artwork(artworks[r["b"]]["path"], r["matches"], "b", img_w, img_h)
        ax = pad + (img_w - im_a.width) // 2
        ay = y + hdr_h + (img_h - im_a.height) // 2
        bx = pad * 2 + img_w + (img_w - im_b.width) // 2
        by = y + hdr_h + (img_h - im_b.height) // 2
        sheet.paste(im_a, (ax, ay))
        sheet.paste(im_b, (bx, by))
        y += row_h

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, quality=92)
    return out_path


# ------------------------------------------------------------------ exécution principale (reprenable)
def _pair_seed(seed: int, group: str, a: int, b: int) -> int:
    h = hashlib.blake2b(f"{seed}|{group}|{a}|{b}".encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(h, "little")


def _config_sig(run_id: str, fill: str, k: int, n_random: int, seed: int, blur_radius: int, ranking: str = "v2_center_align") -> str:
    return f"{run_id}|{ranking}|{fill}|k={k}|r={n_random}|s={seed}|br={blur_radius if fill == 'blur' else 0}"


def _load_progress(progress_path: Path, sig: str) -> dict[tuple[str, int, int], dict]:
    done: dict[tuple[str, int, int], dict] = {}
    if not progress_path.exists():
        return done
    for line in progress_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("sig") == sig:
            done[(rec["group"], int(rec["a"]), int(rec["b"]))] = rec
    return done


def find_dinov3_run(runs_dir: Path, run_name: str | None = None) -> Run:
    from ..runs import list_runs

    if run_name:
        return Run.load(runs_dir / "features" / run_name)
    runs = [
        r for r in list_runs("features", runs_dir=runs_dir)
        if str(r.manifest["params"].get("encoder", "")).startswith("dinov3")
        and not str(r.manifest["params"].get("encoder", "")).endswith("_texture")
        and r.manifest.get("status") == "complete"
        and not r.manifest["params"].get("limit")
        and (Path(r.path) / "regions.npy").exists()
    ]
    if not runs:
        raise RuntimeError("Aucun run DINOv3 complet avec regions.npy trouvé.")
    return runs[-1]


def run_whytest(
    settings,
    features_run: Run,
    validated_pairs: list[Pair],
    *,
    encoder: Encoder | None = None,
    device: str | None = None,
    k: int = 4,
    n_random: int = 10,
    seed: int = 0,
    fills: tuple[str, ...] = FILL_MODES,
    batch_size: int = 32,
    n_boot: int = 2000,
    max_verify_diff: float = 0.01,
    blur_radius: int | None = None,
    resume: bool = True,
    make_sheet: bool = True,
    say: Callable[[str], None] = print,
) -> dict:
    """Exécute le banc d'occultation complet et renvoie le rapport structuré."""
    t0 = time.perf_counter()
    p = features_run.manifest["params"]
    input_size = int(p["input_size"])
    grids = tuple(p.get("region_grids") or DEFAULT_GRIDS)
    patches = patches_per_side(p)
    sq_boxes = [b for _, b in cell_boxes((GRID,), patches)]
    eff_blur = blur_radius if blur_radius is not None else max(16, input_size // 14)

    ids = np.load(features_run.path / "ids.npy")
    status = np.load(features_run.path / "status.npy")
    G = np.load(features_run.path / "global.npy", mmap_mode="r")
    R = np.load(features_run.path / "regions.npy", mmap_mode="r")

    ok_mask = status == OK
    ok_ids = ids[ok_mask]
    row_of = {int(i): r for r, i in enumerate(ids) if status[r] == OK}

    # Vecteurs normalisés L2 pour le tirage exact des voisines proches
    X_ok = np.asarray(G[ok_mask], dtype=np.float32)
    X_ok /= np.maximum(np.linalg.norm(X_ok, axis=1, keepdims=True), 1e-12)

    val_usable = [pr for pr in validated_pairs if pr.status == "validée" and pr.a in row_of and pr.b in row_of]
    val_keys = {(min(pr.a, pr.b), max(pr.a, pr.b)) for pr in val_usable}
    ctrl_pairs = sample_neighbor_pairs(ok_ids, X_ok, n=len(val_usable), seed=seed, exclude=val_keys)
    del X_ok

    say(f"Run de référence : {features_run.id} (input_size={input_size}, patches={patches})")
    say(f"Paires chargées : {len(val_usable)} validées + {len(ctrl_pairs)} voisines proches témoins (graine {seed})")

    all_pairs: list[tuple[str, Pair]] = [("validees", pr) for pr in val_usable] + [("voisines", pr) for pr in ctrl_pairs]
    unique_ids = sorted({pr.a for _, pr in all_pairs} | {pr.b for _, pr in all_pairs})

    conn = db.connect(settings.catalog_path)
    artworks = db.get_artworks(conn, unique_ids)
    meta = get_metadata(conn, unique_ids)
    conn.close()
    sizes = {aid: (artworks[aid]["width"] or 1, artworks[aid]["height"] or 1) for aid in unique_ids if aid in artworks}

    # Correspondances (calculées exactement comme /api/correspond : centrage par case + alignement global)
    cell_means = load_or_compute_cell_means(features_run.path, grids=grids)
    eligible: list[dict] = []
    counts_ge_k = {"validees": {"total": 0, "ge_k": 0}, "voisines": {"total": 0, "ge_k": 0}}
    for grp, pr in all_pairs:
        counts_ge_k[grp]["total"] += 1
        ra = np.asarray(R[row_of[pr.a]], dtype=np.float32)
        rb = np.asarray(R[row_of[pr.b]], dtype=np.float32)
        ga = np.asarray(G[row_of[pr.a]], dtype=np.float32)
        gb = np.asarray(G[row_of[pr.b]], dtype=np.float32)
        matches_all = correspondences(
            ra, rb, sizes[pr.a], sizes[pr.b], grids=grids, k=16, patches=patches,
            cell_means=cell_means, global_a=ga, global_b=gb,
        )
        va = valid_cells_for(ra, sizes[pr.a], grids=grids, patches=patches)
        vb = valid_cells_for(rb, sizes[pr.b], grids=grids, patches=patches)
        if len(matches_all) >= k and len(va) >= k and len(vb) >= k:
            counts_ge_k[grp]["ge_k"] += 1
            eligible.append({
                "group": grp, "a": pr.a, "b": pr.b, "type": pr.type, "origin": pr.origin,
                "n_matches_total": len(matches_all), "matches": matches_all[:k],
                "valid_a": va, "valid_b": vb,
            })

    say(f"Paires avec >= {k} correspondances : "
        f"validées {counts_ge_k['validees']['ge_k']}/{counts_ge_k['validees']['total']}, "
        f"voisines {counts_ge_k['voisines']['ge_k']}/{counts_ge_k['voisines']['total']}")
    if not eligible:
        raise RuntimeError(f"Aucune paire n'atteint {k} correspondances mutuelles.")

    if encoder is None:
        from ..encoders.registry import get_encoder
        enc_kwargs = {"hf_model": p.get("weights"), "input_size": input_size}
        if device is not None:
            enc_kwargs["device"] = device
        encoder = get_encoder(p["encoder"], **enc_kwargs)
        say(f"Encodeur chargé : {encoder.describe()}")

    # Préparation en mémoire des images uniques
    needed_ids = sorted({e["a"] for e in eligible} | {e["b"] for e in eligible})
    preps = {aid: prepare_image(artworks[aid]["path"], input_size, artwork_id=aid) for aid in needed_ids}

    # Étape 1 : vérification sans occultation (écart < max_verify_diff contre global.npy)
    t_ver = time.perf_counter()
    orig_arrays = [to_normalized_array(Image.fromarray(preps[aid].canvas, mode="RGB")) for aid in needed_ids]
    orig_mat = _encode_arrays(encoder, orig_arrays, batch_size=batch_size)
    orig_vecs = {aid: orig_mat[i] for i, aid in enumerate(needed_ids)}

    diffs_cos: list[float] = []
    self_sims: list[float] = []
    for aid in needed_ids:
        v_ref = np.asarray(G[row_of[aid]], dtype=np.float32)
        v_ref /= max(float(np.linalg.norm(v_ref)), 1e-12)
        self_sims.append(float(v_ref @ orig_vecs[aid]))
    for e in eligible:
        va_ref = np.asarray(G[row_of[e["a"]]], dtype=np.float32)
        va_ref /= max(float(np.linalg.norm(va_ref)), 1e-12)
        vb_ref = np.asarray(G[row_of[e["b"]]], dtype=np.float32)
        vb_ref /= max(float(np.linalg.norm(vb_ref)), 1e-12)
        e["cos_run"] = float(va_ref @ vb_ref)
        e["cos_orig"] = float(orig_vecs[e["a"]] @ orig_vecs[e["b"]])
        diffs_cos.append(abs(e["cos_run"] - e["cos_orig"]))

    verify = {
        "n_unique_artworks": len(needed_ids),
        "n_pairs_checked": len(eligible),
        "max_abs_cos_diff": round(float(max(diffs_cos)), 6),
        "mean_abs_cos_diff": round(float(np.mean(diffs_cos)), 6),
        "min_self_cos": round(float(min(self_sims)), 6),
        "threshold": max_verify_diff,
        "ok": bool(max(diffs_cos) < max_verify_diff and min(self_sims) > 1.0 - max_verify_diff),
        "seconds": round(time.perf_counter() - t_ver, 2),
    }
    say(f"Vérification sans occultation ({verify['seconds']} s) : "
        f"écart max cos = {verify['max_abs_cos_diff']:.6f} (moy. {verify['mean_abs_cos_diff']:.6f}), "
        f"auto-cos min = {verify['min_self_cos']:.6f} → {'OK' if verify['ok'] else 'ÉCHEC'}")
    if not verify["ok"]:
        raise RuntimeError(
            f"Écart cosinus sans occultation trop grand ({verify['max_abs_cos_diff']:.4f} >= {max_verify_diff}) : "
            f"le prétraitement ne reproduit pas le run {features_run.id}."
        )

    bench_dir = Path(settings.data_dir) / "bench"
    bench_dir.mkdir(parents=True, exist_ok=True)
    progress_path = bench_dir / "whytest_progress.jsonl"

    fills_out: dict[str, dict] = {}
    records_by_fill: dict[str, list[dict]] = {}
    total_images_encoded = len(needed_ids)

    for fill in fills:
        t_fill = time.perf_counter()
        sig = _config_sig(features_run.id, fill, k, n_random, seed, eff_blur)
        done = _load_progress(progress_path, sig) if resume else {}
        todo = [e for e in eligible if (e["group"], e["a"], e["b"]) not in done]
        say(f"\nRemplissage « {fill} » : {len(done)} paires déjà calculées, {len(todo)} à faire…")

        # Précalcul des vecteurs « centre » (c) une seule fois par œuvre unique nécessaire
        todo_ids = sorted({e["a"] for e in todo} | {e["b"] for e in todo})
        center_vecs: dict[int, np.ndarray] = {}
        center_areas: dict[int, float] = {}
        if todo_ids:
            valid_by_id: dict[int, list[int]] = {}
            for e in todo:
                valid_by_id[e["a"]] = e["valid_a"]
                valid_by_id[e["b"]] = e["valid_b"]
            c_arrs = []
            for aid in todo_ids:
                cc = center_cells_for(valid_by_id[aid], sq_boxes, k=k)
                arr, area = mask_canvas(preps[aid], cc, sq_boxes, fill=fill, blur_radius=eff_blur)
                c_arrs.append(arr)
                center_areas[aid] = area
            c_mat = _encode_arrays(encoder, c_arrs, batch_size=batch_size)
            total_images_encoded += len(todo_ids)
            for i, aid in enumerate(todo_ids):
                center_vecs[aid] = c_mat[i]

        # Traitement des paires par paquets de 4 avec journalisation/sauvegarde incrémentale
        pair_chunk = 4
        with open(progress_path, "a", encoding="utf-8") as prog_f:
            for start in range(0, len(todo), pair_chunk):
                sub = todo[start:start + pair_chunk]
                batch_arrays: list[np.ndarray] = []
                meta_items: list[dict] = []
                for e in sub:
                    a, b = e["a"], e["b"]
                    cells_a_why = [m["cell_a"] for m in e["matches"]]
                    cells_b_why = [m["cell_b"] for m in e["matches"]]
                    arr_a_why, area_a_why = mask_canvas(preps[a], cells_a_why, sq_boxes, fill=fill, blur_radius=eff_blur)
                    arr_b_why, area_b_why = mask_canvas(preps[b], cells_b_why, sq_boxes, fill=fill, blur_radius=eff_blur)
                    off = len(batch_arrays)
                    batch_arrays.extend([arr_a_why, arr_b_why])

                    rng_p = np.random.default_rng(_pair_seed(seed, e["group"], a, b))
                    rand_areas_a, rand_areas_b = [], []
                    for _ in range(n_random):
                        ca = rng_p.choice(e["valid_a"], size=k, replace=False).tolist()
                        cb = rng_p.choice(e["valid_b"], size=k, replace=False).tolist()
                        arr_ra, ar_a = mask_canvas(preps[a], ca, sq_boxes, fill=fill, blur_radius=eff_blur)
                        arr_rb, ar_b = mask_canvas(preps[b], cb, sq_boxes, fill=fill, blur_radius=eff_blur)
                        batch_arrays.extend([arr_ra, arr_rb])
                        rand_areas_a.append(ar_a)
                        rand_areas_b.append(ar_b)
                    meta_items.append({
                        "e": e, "off": off,
                        "area_a_why": area_a_why, "area_b_why": area_b_why,
                        "area_a_rand": float(np.mean(rand_areas_a)), "area_b_rand": float(np.mean(rand_areas_b)),
                    })

                vecs = _encode_arrays(encoder, batch_arrays, batch_size=batch_size)
                total_images_encoded += len(batch_arrays)

                for it in meta_items:
                    e, off = it["e"], it["off"]
                    a, b = e["a"], e["b"]
                    cos0 = e["cos_orig"]
                    vb_orig = orig_vecs[b]

                    va_why, vb_why = vecs[off], vecs[off + 1]
                    cos_a_both = float(va_why @ vb_why)
                    cos_a_one = float(va_why @ vb_orig)

                    r_both, r_one = [], []
                    for t in range(n_random):
                        va_r = vecs[off + 2 + 2 * t]
                        vb_r = vecs[off + 2 + 2 * t + 1]
                        r_both.append(float(va_r @ vb_r))
                        r_one.append(float(va_r @ vb_orig))
                    cos_b_both = float(np.mean(r_both))
                    cos_b_one = float(np.mean(r_one))

                    va_c, vb_c = center_vecs[a], center_vecs[b]
                    cos_c_both = float(va_c @ vb_c)
                    cos_c_one = float(va_c @ vb_orig)

                    rec = {
                        "sig": sig,
                        "group": e["group"], "a": a, "b": b, "type": e["type"], "origin": e["origin"],
                        "n_matches_total": e["n_matches_total"], "matches": e["matches"],
                        "cos_run": round(e["cos_run"], 6), "cos_orig": round(cos0, 6),
                        "both": {
                            "cos_a": round(cos_a_both, 6), "cos_b": round(cos_b_both, 6), "cos_c": round(cos_c_both, 6),
                            "drop_a": round(cos0 - cos_a_both, 6),
                            "drop_b": round(cos0 - cos_b_both, 6),
                            "drop_c": round(cos0 - cos_c_both, 6),
                            "rand_std": round(float(np.std(r_both)), 6),
                        },
                        "one": {
                            "cos_a": round(cos_a_one, 6), "cos_b": round(cos_b_one, 6), "cos_c": round(cos_c_one, 6),
                            "drop_a": round(cos0 - cos_a_one, 6),
                            "drop_b": round(cos0 - cos_b_one, 6),
                            "drop_c": round(cos0 - cos_c_one, 6),
                            "rand_std": round(float(np.std(r_one)), 6),
                        },
                        "areas": {
                            "a": {"area_a": round(it["area_a_why"], 4), "area_b": round(it["area_b_why"], 4),
                                  "area_both": round(0.5 * (it["area_a_why"] + it["area_b_why"]), 4)},
                            "b": {"area_a": round(it["area_a_rand"], 4), "area_b": round(it["area_b_rand"], 4),
                                  "area_both": round(0.5 * (it["area_a_rand"] + it["area_b_rand"]), 4)},
                            "c": {"area_a": round(center_areas[a], 4), "area_b": round(center_areas[b], 4),
                                  "area_both": round(0.5 * (center_areas[a] + center_areas[b]), 4)},
                        },
                    }
                    done[(e["group"], a, b)] = rec
                    prog_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                prog_f.flush()
                done_now = min(start + pair_chunk, len(todo))
                if done_now == len(todo) or done_now % 20 == 0:
                    say(f"  [{fill}] {done_now}/{len(todo)} paires ({time.perf_counter() - t_fill:.1f} s)")

        if fill == "blur":
            for prep in preps.values():
                prep.blurred = None

        ordered = [done[(e["group"], e["a"], e["b"])] for e in eligible]
        records_by_fill[fill] = ordered
        fills_out[fill] = {
            **aggregate_fill(ordered, n_boot=n_boot, seed=seed),
            "seconds": round(time.perf_counter() - t_fill, 2),
        }

    # Planche de 6 paires (sur le remplissage principal « mean », ou le premier disponible)
    primary_fill = "mean" if "mean" in records_by_fill else fills[0]
    top, bottom = select_sheet_pairs(records_by_fill[primary_fill])
    sheet_path = None
    if make_sheet and (top or bottom):
        sheet_path = str(render_contact_sheet(top, bottom, artworks, meta, bench_dir / "whytest_planche.jpg"))
        say(f"\nPlanche visuelle : {sheet_path}")

    def _brief_sheet(r: dict) -> dict:
        return {
            "a": r["a"], "b": r["b"], "type": r["type"], "group": r["group"],
            "cos_orig": r["cos_orig"],
            "drop_a": r["both"]["drop_a"], "drop_b": r["both"]["drop_b"], "drop_c": r["both"]["drop_c"],
            "drop_a_one": r["one"]["drop_a"], "drop_b_one": r["one"]["drop_b"], "drop_c_one": r["one"]["drop_c"],
            "label_a": meta.get(r["a"], {}), "label_b": meta.get(r["b"], {}),
            "matches": r["matches"],
        }

    elapsed = round(time.perf_counter() - t0, 2)
    report = {
        "features": features_run.id,
        "encoder": p.get("encoder"),
        "input_size": input_size,
        "patches": patches,
        "params": {"k": k, "n_random": n_random, "seed": seed, "fills": list(fills),
                   "blur_radius": eff_blur, "n_boot": n_boot},
        "counts": counts_ge_k,
        "verification": verify,
        "results": fills_out,
        "sheet": {
            "path": sheet_path,
            "fill": primary_fill,
            "top": [_brief_sheet(r) for r in top],
            "bottom": [_brief_sheet(r) for r in bottom],
        },
        "pairs": {fill: [{kk: vv for kk, vv in r.items() if kk != "sig"} for r in recs]
                  for fill, recs in records_by_fill.items()},
        "total_images_encoded": total_images_encoded,
        "seconds": elapsed,
    }
    out_json = bench_dir / "whytest_report.json"
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    say(f"Rapport : {out_json}  ({total_images_encoded} images encodées en {elapsed:.1f} s)")
    return report
