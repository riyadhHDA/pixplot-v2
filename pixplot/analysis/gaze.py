"""Évaluation oculométrique des zones mises en avant par PixPlot sur le jeu AVAtt.

Question : les zones que PixPlot montre à l'historien — correspondances 4 × 4 du bouton
« Pourquoi ? » (``correspondences.py``, ARCHITECTURE §§ 39–40) et zones trouvées par une
phrase (``search_zones``, index SigLIP 2 de 1,6 million de zones) — coïncident-elles avec
les zones que regardent les observateurs humains ?

Jeu de données : **AVAtt** (*AVAtt: A Free-Viewing Eye-Tracking Dataset and Benchmark for
Visual Attention on Paintings*, Kerkouri et al., arXiv:2610.30481, 2026) — 283 lignes
(282 peintures uniques, 1 doublon signalé ``avatt_0219`` → ``avatt_0218``), 152 volontaires
en observation libre, 121 426 fixations. Les données oculométriques sont en CC0 1.0 ; les
images restent strictement en local dans ``data/`` (jamais dans git).

Trois mesures, chacune face au hasard et à deux témoins naïfs sans apprentissage
(**biais vers le centre** et **contraste local**), avec intervalles de confiance à 95 %
par tirage avec remise (*bootstrap*) sur les peintures :

a. **« Pourquoi ? »** (cases 4 × 4 des correspondances DINOv3) : part des fixations
   humaines dans les cases montrées, enrichissement (rapport part des fixations / surface)
   et NSS (*Normalized Scanpath Saliency*) sur le masque binaire des cases, comparés au
   hasard (même nombre de cases), au biais central, au contraste local, ainsi qu'à l'ancien
   classement d'avant le § 40.
b. **``search_zones``** (zones 2 × 2 et 4 × 4 trouvées par une phrase SigLIP 2) : sur un jeu
   fixe de 20 requêtes iconographiques en français et sur les titres des œuvres, la zone
   renvoyée est-elle plus regardée que les autres cases de la même grille de la même peinture ?
c. **Témoins naïfs** : biais central (gaussienne centrée) et contraste local (sans
   apprentissage), évalués à la fois sur les mêmes grilles (top-k cases) et en NSS continu.

Précaution de lecture : une zone peu regardée lors d'une observation libre de quelques
secondes peut rester tout à fait pertinente pour une comparaison d'histoire de l'art
(un fond architectural, une bordure, un drapé, une touche de pinceau).
"""

from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from ..catalog.ingest import dhash
from ..catalog.wikiart_names import MAX_BITS, MIN_MARGIN, _popcount
from ..features.extract import OK
from ..features.regions import DEFAULT_GRIDS
from ..index.regions import cell_boxes, patches_per_side, square_to_image
from ..index.textzones import ZoneIndex, find_zone_index, zone_boxes
from ..runs import Run, list_runs
from .correspondences import GRID, cells_of, correspondences, load_or_compute_cell_means

# 20 requêtes iconographiques courantes (en français, comme dans l'Atlas), fixées d'avance.
DEFAULT_ZONE_QUERIES: tuple[str, ...] = (
    "visage",
    "portrait d'une femme",
    "mains",
    "enfant",
    "personnage à cheval",
    "groupe de personnages",
    "église ou clocher",
    "pont",
    "maison",
    "fenêtre",
    "bateau ou voilier",
    "arbre",
    "ciel et nuages",
    "montagne",
    "rivière ou mer",
    "fleurs",
    "table",
    "fruit ou coupe",
    "chien",
    "oiseau",
)

PALETTE_BOXES = (
    (0, 229, 255),    # 1 : cyan vif
    (74, 222, 128),   # 2 : vert clair
    (250, 204, 21),   # 3 : jaune
    (244, 114, 182),  # 4 : rose
)


@dataclass
class AvattPainting:
    """Une peinture d'AVAtt avec son cadre dans le stimulus et ses fixations normalisées."""

    image_id: str
    title: str
    artist: str
    year: str
    movement: str
    genre: str
    copyright_status: str
    exposure_s: float
    n_observers: int
    painting_box: tuple[int, int, int, int]   # (x0, y0, x1, y1) dans le stimulus 1600×900
    image_path: Path
    saliency_path: Path | None
    fixations: np.ndarray                     # (M, 2) float32 en fractions [0, 1] de la peinture
    n_fixations_raw: int
    duplicate_of: str = ""
    artwork_id: int | None = None
    dhash_bits: int = -1
    dhash_margin: int = -1


# ------------------------------------------------------------------ chargement AVAtt et rattachement dHash
def load_avatt_fixations(
    scanpath_path: Path,
    painting_box: tuple[int, int, int, int],
) -> tuple[np.ndarray, int]:
    """Lit ``scanpaths/<id>.jsonl`` et renvoie les fixations dans la peinture en coordonnées [0, 1]."""
    x0, y0, x1, y1 = painting_box
    w = max(x1 - x0, 1)
    h = max(y1 - y0, 1)
    pts: list[tuple[float, float]] = []
    n_raw = 0
    with open(scanpath_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obs = json.loads(line)
            for fx in obs.get("fixations", ()):
                n_raw += 1
                x, y = float(fx["x"]), float(fx["y"])
                if x0 <= x < x1 and y0 <= y < y1:
                    pts.append(((x - x0) / w, (y - y0) / h))
    arr = np.asarray(pts, dtype=np.float32).reshape(-1, 2)
    return arr, n_raw


def load_avatt(avatt_dir: Path, include_duplicates: bool = False) -> tuple[list[AvattPainting], dict]:
    """Charge les métadonnées et fixations d'AVAtt depuis ``avatt_dir``."""
    avatt_dir = Path(avatt_dir)
    meta_path = avatt_dir / "metadata.csv"
    if not meta_path.exists():
        raise FileNotFoundError(f"metadata.csv introuvable dans {avatt_dir}")
    with open(meta_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    paintings: list[AvattPainting] = []
    n_duplicates = 0
    tot_raw = 0
    tot_in = 0
    for r in rows:
        dup = (r.get("duplicate_of") or "").strip()
        if dup and not include_duplicates:
            n_duplicates += 1
            continue
        iid = r["image_id"].strip()
        box = (int(r["painting_x0"]), int(r["painting_y0"]), int(r["painting_x1"]), int(r["painting_y1"]))
        img_path = avatt_dir / "images" / f"{iid}.jpg"
        sal_path = avatt_dir / "saliency_maps" / f"{iid}.png"
        scan_path = avatt_dir / "scanpaths" / f"{iid}.jsonl"
        fix, n_raw = load_avatt_fixations(scan_path, box)
        tot_raw += n_raw
        tot_in += len(fix)
        paintings.append(
            AvattPainting(
                image_id=iid,
                title=(r.get("title") or "").strip(),
                artist=(r.get("artist") or "").strip(),
                year=(r.get("year") or "").strip(),
                movement=(r.get("movement") or "").strip(),
                genre=(r.get("genre") or "").strip(),
                copyright_status=(r.get("copyright_status") or "").strip(),
                exposure_s=float(r.get("exposure_s") or 0.0),
                n_observers=int(r.get("n_observers") or 0),
                painting_box=box,
                image_path=img_path,
                saliency_path=sal_path if sal_path.exists() else None,
                fixations=fix,
                n_fixations_raw=n_raw,
                duplicate_of=dup,
            )
        )
    summary = {
        "rows_total": len(rows),
        "duplicates_excluded": n_duplicates,
        "paintings_loaded": len(paintings),
        "fixations_raw": tot_raw,
        "fixations_in_painting": tot_in,
        "fixations_in_ratio": round(tot_in / max(tot_raw, 1), 4),
    }
    return paintings, summary


def crop_painting(painting: AvattPainting) -> Image.Image:
    """Ouvre le stimulus AVAtt et recadre exactement la peinture (hors bordures grises)."""
    with Image.open(painting.image_path) as im:
        return im.convert("RGB").crop(painting.painting_box)


def match_avatt_to_catalog(
    paintings: list[AvattPainting],
    catalog_path: Path,
    max_bits: int = MAX_BITS,
    min_margin: int = MIN_MARGIN,
) -> dict:
    """Rattache les peintures d'AVAtt au catalogue par dHash 64 bits (règle ``wikiart_names.py``).

    Modifie ``artwork_id``, ``dhash_bits`` et ``dhash_margin`` sur place. Si deux peintures
    AVAtt pointaient vers la même œuvre du catalogue, seule la plus proche en bits est gardée.
    """
    conn = sqlite3.connect(catalog_path)
    try:
        rows = conn.execute(
            "SELECT id, dhash FROM artworks WHERE status = 'ok' AND dhash IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return {"matched": 0, "unmatched": len(paintings), "rejected_margin": 0, "max_bits": max_bits, "min_margin": min_margin}

    w_ids = np.array([int(r[0]) for r in rows], dtype=np.int64)
    w_hashes = np.array([int(r[1], 16) for r in rows], dtype=np.uint64)

    best_for_aid: dict[int, AvattPainting] = {}
    rejected_margin = 0
    for p in paintings:
        crop = crop_painting(p)
        crop.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
        h = int(dhash(crop), 16)
        d = _popcount(w_hashes ^ np.uint64(h))
        order = np.argsort(d)
        b1 = int(d[order[0]])
        b2 = int(d[order[1]]) if len(order) > 1 else 99
        margin = b2 - b1
        if b1 <= max_bits and margin >= min_margin:
            aid = int(w_ids[order[0]])
            prev = best_for_aid.get(aid)
            if prev is None or b1 < prev.dhash_bits:
                if prev is not None:
                    prev.artwork_id = None
                    prev.dhash_bits = -1
                    prev.dhash_margin = -1
                p.artwork_id = aid
                p.dhash_bits = b1
                p.dhash_margin = margin
                best_for_aid[aid] = p
        elif b1 <= max_bits:
            rejected_margin += 1

    matched = sum(1 for p in paintings if p.artwork_id is not None)
    return {
        "total": len(paintings),
        "matched": matched,
        "unmatched": len(paintings) - matched,
        "rejected_margin": rejected_margin,
        "max_bits": max_bits,
        "min_margin": min_margin,
    }


# ------------------------------------------------------------------ métriques oculométriques et témoins naïfs
def boxes_metrics(
    fixations: np.ndarray,
    boxes: list[list[float] | tuple[float, float, float, float]],
    grid_res: int = 128,
) -> dict[str, float]:
    """Mesure la coïncidence entre un ensemble de boîtes normalisées et les fixations humaines.

    Renvoie :
    - ``fix_share``  : part des fixations tombant dans l'union des boîtes ;
    - ``area``       : part de surface de la peinture couverte par l'union des boîtes ;
    - ``enrichment`` : densité relative ``fix_share / area`` (1,0 = uniforme) ;
    - ``nss``        : *Normalized Scanpath Saliency* du masque binaire des boîtes
                       ``(fix_share - area) / sqrt(area * (1 - area))`` (0 = hasard uniforme).
    """
    if not boxes or len(fixations) == 0:
        return {"fix_share": 0.0, "area": 0.0, "enrichment": 0.0, "nss": 0.0}

    u = fixations[:, 0]
    v = fixations[:, 1]
    hit = np.zeros(len(fixations), dtype=bool)
    mask = np.zeros((grid_res, grid_res), dtype=bool)
    for b in boxes:
        x0, y0, x1, y1 = float(b[0]), float(b[1]), float(b[2]), float(b[3])
        if x1 <= x0 or y1 <= y0:
            continue
        in_x = (u >= x0) & ((u <= x1) if x1 >= 1.0 - 1e-6 else (u < x1))
        in_y = (v >= y0) & ((v <= y1) if y1 >= 1.0 - 1e-6 else (v < y1))
        hit |= in_x & in_y
        ix0 = max(0, min(grid_res, int(round(x0 * grid_res))))
        iy0 = max(0, min(grid_res, int(round(y0 * grid_res))))
        ix1 = max(0, min(grid_res, int(round(x1 * grid_res))))
        iy1 = max(0, min(grid_res, int(round(y1 * grid_res))))
        if ix1 > ix0 and iy1 > iy0:
            mask[iy0:iy1, ix0:ix1] = True

    area = float(mask.mean())
    fix_share = float(hit.mean())
    enrichment = (fix_share / area) if area > 1e-9 else 0.0
    if 1e-6 < area < 1.0 - 1e-6:
        nss = (fix_share - area) / float(np.sqrt(area * (1.0 - area)))
    else:
        nss = 0.0
    return {
        "fix_share": fix_share,
        "area": area,
        "enrichment": enrichment,
        "nss": nss,
    }


def map_nss(sal_map: np.ndarray, fixations: np.ndarray) -> float:
    """NSS continu d'une carte de saillance 2D ``(H, W)`` sur des fixations normalisées [0, 1]."""
    if len(fixations) == 0:
        return 0.0
    m = np.asarray(sal_map, dtype=np.float64)
    std = float(m.std())
    if std <= 1e-12:
        return 0.0
    z = (m - float(m.mean())) / std
    h, w = z.shape
    ix = np.clip((fixations[:, 0] * w).astype(np.int64), 0, w - 1)
    iy = np.clip((fixations[:, 1] * h).astype(np.int64), 0, h - 1)
    return float(z[iy, ix].mean())


def center_bias_map(size: int = 128, sigma: float = 0.25) -> np.ndarray:
    """Carte naïve de biais vers le centre : gaussienne isotrope centrée en (0,5 ; 0,5)."""
    coords = (np.arange(size, dtype=np.float32) + 0.5) / size
    yy, xx = np.meshgrid(coords, coords, indexing="ij")
    d2 = (xx - 0.5) ** 2 + (yy - 0.5) ** 2
    return np.exp(-d2 / (2.0 * sigma * sigma)).astype(np.float32)


def local_contrast_map(img: Image.Image, size: int = 128) -> np.ndarray:
    """Carte de saillance naïve sans apprentissage : contraste centre-périphérie + gradient local."""
    small = img.convert("RGB").resize((size, size), Image.Resampling.BILINEAR)
    arr = np.asarray(small, dtype=np.float32) / 255.0
    blur_r = max(2.0, size * 0.04)
    blurred = np.asarray(small.filter(ImageFilter.GaussianBlur(radius=blur_r)), dtype=np.float32) / 255.0
    cs = np.abs(arr - blurred).mean(axis=2)

    lum = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
    # Gradient de Sobel 3 × 3
    pad = np.pad(lum, 1, mode="edge")
    gx = (
        -pad[:-2, :-2] + pad[:-2, 2:]
        - 2.0 * pad[1:-1, :-2] + 2.0 * pad[1:-1, 2:]
        - pad[2:, :-2] + pad[2:, 2:]
    )
    gy = (
        -pad[:-2, :-2] - 2.0 * pad[:-2, 1:-1] - pad[:-2, 2:]
        + pad[2:, :-2] + 2.0 * pad[2:, 1:-1] + pad[2:, 2:]
    )
    grad = np.hypot(gx, gy)

    def _norm(x: np.ndarray) -> np.ndarray:
        s = float(x.std())
        return (x - float(x.mean())) / s if s > 1e-8 else np.zeros_like(x)

    comb = _norm(cs) + _norm(grad)
    lo, hi = float(comb.min()), float(comb.max())
    if hi > lo + 1e-8:
        scaled = ((comb - lo) / (hi - lo) * 255.0).astype(np.uint8)
        smooth_r = max(1.5, size * 0.025)
        out = np.asarray(
            Image.fromarray(scaled, mode="L").filter(ImageFilter.GaussianBlur(radius=smooth_r)),
            dtype=np.float32,
        ) / 255.0
        return out
    return np.zeros((size, size), dtype=np.float32)


def top_k_cells_from_map(
    sal_map: np.ndarray,
    valid_boxes: dict[int, list[float]],
    k: int,
) -> list[int]:
    """Sélectionne les ``k`` cases valides ayant la plus forte valeur moyenne dans ``sal_map``."""
    h, w = sal_map.shape
    scored: list[tuple[float, int]] = []
    for cid, b in valid_boxes.items():
        ix0 = max(0, min(w - 1, int(round(b[0] * w))))
        iy0 = max(0, min(h - 1, int(round(b[1] * h))))
        ix1 = max(ix0 + 1, min(w, int(round(b[2] * w))))
        iy1 = max(iy0 + 1, min(h, int(round(b[3] * h))))
        scored.append((float(sal_map[iy0:iy1, ix0:ix1].mean()), cid))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [cid for _, cid in scored[:k]]


# ------------------------------------------------------------------ statistiques bootstrap sur les peintures
def bootstrap_summary(
    values: np.ndarray,
    n_boot: int = 2000,
    seed: int = 0,
    level: float = 0.95,
) -> dict:
    """Moyenne, médiane et IC 95 % par tirage avec remise sur les peintures."""
    v = np.asarray(values, dtype=np.float64)
    n = len(v)
    if n == 0:
        return {"n": 0}
    rng = np.random.default_rng(seed)
    idx = rng.integers(n, size=(n_boot, n))
    boot = v[idx]
    lo_q, hi_q = (1.0 - level) / 2.0 * 100.0, (1.0 + level) / 2.0 * 100.0
    means = boot.mean(axis=1)
    meds = np.median(boot, axis=1)
    return {
        "n": n,
        "mean": round(float(v.mean()), 4),
        "mean_ci": [round(float(np.percentile(means, lo_q)), 4), round(float(np.percentile(means, hi_q)), 4)],
        "median": round(float(np.median(v)), 4),
        "median_ci": [round(float(np.percentile(meds, lo_q)), 4), round(float(np.percentile(meds, hi_q)), 4)],
    }


def bootstrap_paired(
    a: np.ndarray,
    b: np.ndarray,
    n_boot: int = 2000,
    seed: int = 0,
    level: float = 0.95,
) -> dict:
    """Écart apparié ``a − b`` avec IC 95 % et p-valeur bilatérale (bootstrap sur les peintures)."""
    va = np.asarray(a, dtype=np.float64)
    vb = np.asarray(b, dtype=np.float64)
    d = va - vb
    n = len(d)
    if n == 0:
        return {"n": 0}
    rng = np.random.default_rng(seed)
    idx = rng.integers(n, size=(n_boot, n))
    boot_d = d[idx]
    lo_q, hi_q = (1.0 - level) / 2.0 * 100.0, (1.0 + level) / 2.0 * 100.0
    means = boot_d.mean(axis=1)
    meds = np.median(boot_d, axis=1)
    p_mean = float(min(1.0, 2.0 * min((means <= 0).mean(), (means >= 0).mean())))
    p_med = float(min(1.0, 2.0 * min((meds <= 0).mean(), (meds >= 0).mean())))
    return {
        "n": n,
        "mean_diff": round(float(d.mean()), 4),
        "mean_ci": [round(float(np.percentile(means, lo_q)), 4), round(float(np.percentile(means, hi_q)), 4)],
        "p_mean": round(p_mean, 4),
        "median_diff": round(float(np.median(d)), 4),
        "median_ci": [round(float(np.percentile(meds, lo_q)), 4), round(float(np.percentile(meds, hi_q)), 4)],
        "p_median": round(p_med, 4),
        "share_pos": round(float((d > 0).mean()), 4),
    }


def _summarize_conditions(
    records: list[dict],
    keys: tuple[str, ...],
    metrics: tuple[str, ...] = ("fix_share", "area", "enrichment", "nss"),
    n_boot: int = 2000,
    seed: int = 0,
) -> dict:
    out: dict = {"n_paintings": len(records), "conditions": {}, "paired": {}}
    if not records:
        return out
    for k in keys:
        out["conditions"][k] = {
            m: bootstrap_summary(np.array([r[k][m] for r in records]), n_boot=n_boot, seed=seed)
            for m in metrics
        }
    primary = keys[0]
    for other in keys[1:]:
        out["paired"][f"{primary}_minus_{other}"] = {
            m: bootstrap_paired(
                np.array([r[primary][m] for r in records]),
                np.array([r[other][m] for r in records]),
                n_boot=n_boot,
                seed=seed,
            )
            for m in ("fix_share", "enrichment", "nss")
        }
    return out


# ------------------------------------------------------------------ mesure (a) : « Pourquoi ? » (4 × 4 DINOv3)
def _find_forme_run(runs_dir: Path) -> Run:
    runs = [
        r for r in list_runs("features", runs_dir=runs_dir)
        if (Path(r.path) / "regions.npy").exists() and "texture" not in r.manifest["name"]
    ]
    if not runs:
        raise RuntimeError("Aucun run de vecteurs avec régions (DINOv3) trouvé.")
    # Préfère DINOv3 s'il existe
    dino = [r for r in runs if "dinov3" in r.manifest["name"]]
    return dino[-1] if dino else runs[-1]


def evaluate_why(
    paintings: list[AvattPainting],
    catalog_path: Path,
    runs_dir: Path,
    *,
    neighbor_pool: str = "avatt",
    k: int = 4,
    n_random: int = 50,
    n_boot: int = 2000,
    seed: int = 0,
    say: Callable[[str], None] = print,
) -> dict:
    """Mesure (a) : coïncidence entre les cases 4 × 4 du « Pourquoi ? » et les fixations AVAtt.

    ``neighbor_pool`` :
    - ``"avatt"``   : 1ʳᵉ voisine parmi les autres peintures d'AVAtt rattachées ;
    - ``"corpus"``  : 1ʳᵉ voisine dans tout le corpus (hors doublons cos >= 0,98).
    """
    matched = [p for p in paintings if p.artwork_id is not None and len(p.fixations) > 0]
    if len(matched) < 2:
        raise RuntimeError(f"Trop peu de peintures AVAtt rattachées ({len(matched)}) pour évaluer « Pourquoi ? ».")

    run = _find_forme_run(runs_dir)
    p_run = Path(run.path)
    ids = np.load(p_run / "ids.npy")
    status = np.load(p_run / "status.npy")
    G = np.load(p_run / "global.npy", mmap_mode="r")
    R = np.load(p_run / "regions.npy", mmap_mode="r")
    row_of = {int(aid): i for i, aid in enumerate(ids.tolist()) if status[i] == OK}

    params = run.manifest.get("params", {})
    grids = tuple(params.get("region_grids", DEFAULT_GRIDS))
    patches = patches_per_side(params)
    sq_boxes = [b for _, b in cell_boxes((GRID,), patches)]
    cell_means = load_or_compute_cell_means(p_run, grids=grids)

    conn = sqlite3.connect(catalog_path)
    try:
        sizes = {int(r[0]): (int(r[1] or 1), int(r[2] or 1)) for r in conn.execute("SELECT id, width, height FROM artworks")}
    finally:
        conn.close()

    matched = [p for p in matched if p.artwork_id in row_of]
    avatt_rows = np.array([row_of[p.artwork_id] for p in matched], dtype=np.int64)
    G_avatt = np.asarray(G[avatt_rows], dtype=np.float32)
    G_avatt /= np.maximum(np.linalg.norm(G_avatt, axis=1, keepdims=True), 1e-12)

    # Trouve la 1ʳᵉ voisine en forme pour chaque peinture AVAtt
    neighbors: list[tuple[AvattPainting, int, float, str]] = []
    if neighbor_pool == "avatt":
        sim = G_avatt @ G_avatt.T
        np.fill_diagonal(sim, -np.inf)
        for i, p in enumerate(matched):
            # Exclut les quasi-doublons (cos >= 0,98)
            s_row = np.where(sim[i] >= 0.98, -np.inf, sim[i])
            j = int(np.argmax(s_row))
            nb = matched[j]
            neighbors.append((p, int(nb.artwork_id), float(s_row[j]), nb.image_id))
    elif neighbor_pool == "corpus":
        ok_idx = np.flatnonzero(status == OK)
        best_sim = np.full(len(matched), -np.inf, dtype=np.float32)
        best_aid = np.full(len(matched), -1, dtype=np.int64)
        for s in range(0, len(ok_idx), 8192):
            blk_idx = ok_idx[s:s + 8192]
            blk = np.asarray(G[blk_idx], dtype=np.float32)
            blk /= np.maximum(np.linalg.norm(blk, axis=1, keepdims=True), 1e-12)
            cs = G_avatt @ blk.T
            blk_ids = ids[blk_idx]
            for i, p in enumerate(matched):
                row_s = cs[i]
                row_s = np.where((blk_ids == p.artwork_id) | (row_s >= 0.98), -np.inf, row_s)
                j = int(np.argmax(row_s))
                if row_s[j] > best_sim[i]:
                    best_sim[i] = float(row_s[j])
                    best_aid[i] = int(blk_ids[j])
        for i, p in enumerate(matched):
            neighbors.append((p, int(best_aid[i]), float(best_sim[i]), f"#{int(best_aid[i])}"))
    else:
        raise ValueError(f"neighbor_pool inconnu : {neighbor_pool}")

    cmap = center_bias_map(128)
    rng = np.random.default_rng(seed)
    records: list[dict] = []
    continuous_center_nss: list[float] = []
    continuous_contrast_nss: list[float] = []
    n_zero_corr = 0
    n_full_k = 0

    for p, nb_aid, nb_cos, nb_label in neighbors:
        ra, rb = row_of[p.artwork_id], row_of[nb_aid]
        reg_a = np.asarray(R[ra], dtype=np.float32)
        reg_b = np.asarray(R[rb], dtype=np.float32)
        ga = np.asarray(G[ra], dtype=np.float32)
        gb = np.asarray(G[rb], dtype=np.float32)
        sz_a = sizes.get(p.artwork_id, (1, 1))
        sz_b = sizes.get(nb_aid, (1, 1))

        # Cases valides de A (même règle que correspondences.match)
        cvecs_a = cells_of(reg_a, grids)
        all_boxes_a = [square_to_image(b, *sz_a) for b in sq_boxes]
        valid_boxes = {
            i: bx for i, (bx, v) in enumerate(zip(all_boxes_a, cvecs_a))
            if bx is not None and float(np.linalg.norm(v)) > 1e-6
        }

        corr_new = correspondences(
            reg_a, reg_b, sz_a, sz_b, grids=grids, k=k, patches=patches,
            cell_means=cell_means, global_a=ga, global_b=gb,
        )
        corr_old = correspondences(
            reg_a, reg_b, sz_a, sz_b, grids=grids, k=k, patches=patches,
            cell_means=None, global_a=None, global_b=None,
        )

        # Cartes naïves sur la peinture recadrée
        lmap = local_contrast_map(crop_painting(p), size=128)
        continuous_center_nss.append(map_nss(cmap, p.fixations))
        continuous_contrast_nss.append(map_nss(lmap, p.fixations))

        if not corr_new:
            n_zero_corr += 1
            continue
        k_eff = len(corr_new)
        if k_eff == k:
            n_full_k += 1

        why_boxes = [m["box_a"] for m in corr_new]
        why_cells = [m["cell_a"] for m in corr_new]
        m_why = boxes_metrics(p.fixations, why_boxes)

        # Ancien « Pourquoi ? » (avant § 40), même nombre de cases k_eff
        old_boxes = [m["box_a"] for m in corr_old[:k_eff]]
        m_old = boxes_metrics(p.fixations, old_boxes) if old_boxes else {"fix_share": 0.0, "area": 0.0, "enrichment": 0.0, "nss": 0.0}

        # Témoin hasard : n_random tirages de k_eff cases valides
        v_ids = sorted(valid_boxes.keys())
        r_shares, r_areas, r_enr, r_nss = [], [], [], []
        for _ in range(n_random):
            chosen = rng.choice(v_ids, size=min(k_eff, len(v_ids)), replace=False)
            rm = boxes_metrics(p.fixations, [valid_boxes[int(c)] for c in chosen])
            r_shares.append(rm["fix_share"])
            r_areas.append(rm["area"])
            r_enr.append(rm["enrichment"])
            r_nss.append(rm["nss"])
        m_rand = {
            "fix_share": float(np.mean(r_shares)),
            "area": float(np.mean(r_areas)),
            "enrichment": float(np.mean(r_enr)),
            "nss": float(np.mean(r_nss)),
        }

        # Témoins naïfs sur la même grille 4 × 4 (top-k_eff cases)
        c_cells = top_k_cells_from_map(cmap, valid_boxes, k_eff)
        m_center = boxes_metrics(p.fixations, [valid_boxes[c] for c in c_cells])
        l_cells = top_k_cells_from_map(lmap, valid_boxes, k_eff)
        m_contrast = boxes_metrics(p.fixations, [valid_boxes[c] for c in l_cells])

        records.append({
            "image_id": p.image_id,
            "artwork_id": p.artwork_id,
            "title": p.title,
            "artist": p.artist,
            "movement": p.movement,
            "neighbor_id": nb_aid,
            "neighbor_label": nb_label,
            "neighbor_cos": round(nb_cos, 4),
            "k_eff": k_eff,
            "why_cells": why_cells,
            "why_boxes": why_boxes,
            "why": m_why,
            "why_old": m_old,
            "random": m_rand,
            "center": m_center,
            "contrast": m_contrast,
        })

    summary = _summarize_conditions(
        records,
        keys=("why", "random", "center", "contrast", "why_old"),
        n_boot=n_boot,
        seed=seed,
    )
    summary["neighbor_pool"] = neighbor_pool
    summary["run_id"] = run.id
    summary["n_matched"] = len(matched)
    summary["n_zero_correspondences"] = n_zero_corr
    summary["n_full_k"] = n_full_k
    summary["cos_median"] = round(float(np.median([r["neighbor_cos"] for r in records])), 4) if records else 0.0
    summary["continuous_baselines"] = {
        "center_nss": bootstrap_summary(np.array(continuous_center_nss), n_boot=n_boot, seed=seed),
        "contrast_nss": bootstrap_summary(np.array(continuous_contrast_nss), n_boot=n_boot, seed=seed),
    }
    summary["records"] = records
    say(f"  Pourquoi ({neighbor_pool}) : {len(records)}/{len(matched)} peintures ({n_full_k} avec {k} zones, cos méd. {summary['cos_median']:.3f})")
    return summary


# ------------------------------------------------------------------ mesure (b) : search_zones (SigLIP 2)
def _eval_single_zone(
    painting: AvattPainting,
    grid: int,
    box: list[float],
    cmap: np.ndarray,
    lmap: np.ndarray,
) -> dict:
    """Évalue une zone renvoyée (grille 2×2 ou 4×4) contre toutes les cases de la même grille."""
    grid_boxes = {i: list(b) for i, (g, b) in enumerate(zone_boxes((grid,)))}
    m_zone = boxes_metrics(painting.fixations, [box])

    # Toutes les cases de la même grille → témoin au hasard exact + rang humain de la zone
    all_shares = [boxes_metrics(painting.fixations, [b])["fix_share"] for b in grid_boxes.values()]
    n_cells = len(all_shares)
    # Rang relatif (1,0 = case la plus regardée, 0,0 = la moins regardée ; 0,5 au hasard)
    better = sum(1 for s in all_shares if s > m_zone["fix_share"] + 1e-9)
    equal = sum(1 for s in all_shares if abs(s - m_zone["fix_share"]) <= 1e-9)
    rank_0 = better + 0.5 * max(equal - 1, 0)
    rank_pct = 1.0 - rank_0 / max(n_cells - 1, 1)

    m_rand = {
        "fix_share": 1.0 / n_cells,
        "area": 1.0 / n_cells,
        "enrichment": 1.0,
        "nss": 0.0,
        "rank_pct": 0.5,
    }
    c_cell = top_k_cells_from_map(cmap, grid_boxes, 1)[0]
    m_center = boxes_metrics(painting.fixations, [grid_boxes[c_cell]])
    l_cell = top_k_cells_from_map(lmap, grid_boxes, 1)[0]
    m_contrast = boxes_metrics(painting.fixations, [grid_boxes[l_cell]])

    # Rang relatif des témoins
    for m_obj in (m_center, m_contrast):
        b_cnt = sum(1 for s in all_shares if s > m_obj["fix_share"] + 1e-9)
        e_cnt = sum(1 for s in all_shares if abs(s - m_obj["fix_share"]) <= 1e-9)
        m_obj["rank_pct"] = 1.0 - (b_cnt + 0.5 * max(e_cnt - 1, 0)) / max(n_cells - 1, 1)

    m_zone["rank_pct"] = rank_pct
    return {
        "zone": m_zone,
        "random": m_rand,
        "center": m_center,
        "contrast": m_contrast,
    }


def evaluate_search_zones(
    paintings: list[AvattPainting],
    runs_dir: Path,
    *,
    queries: tuple[str, ...] = DEFAULT_ZONE_QUERIES,
    top_k_per_query: int = 15,
    encoder=None,
    n_boot: int = 2000,
    seed: int = 0,
    say: Callable[[str], None] = print,
) -> dict:
    """Mesure (b) : les zones renvoyées par ``search_zones`` sont-elles plus regardées ?

    Deux protocoles sur les peintures AVAtt rattachées :
    1. ``queries`` : 20 requêtes iconographiques fixes en français ; pour chaque requête, les
       ``top_k_per_query`` meilleures peintures AVAtt dans ``ZoneIndex`` et la zone renvoyée.
    2. ``titles``  : pour chaque peinture AVAtt ayant un titre non vide, la meilleure zone de
       cette peinture pour son propre titre parmi ses 20 zones SigLIP 2.

    Pour respecter l'indépendance entre peintures, les intervalles de confiance bootstrap sont
    calculés **sur les peintures** (moyenne par peinture lorsqu'une peinture répond à plusieurs
    requêtes).
    """
    z_run = find_zone_index(runs_dir)
    if z_run is None:
        raise RuntimeError("Index des zones textuelles absent : lancez `pixplot zones`.")
    z_index = ZoneIndex(z_run)

    matched = [p for p in paintings if p.artwork_id is not None and len(p.fixations) > 0]
    by_aid = {p.artwork_id: p for p in matched}
    allowed = set(by_aid.keys())

    if encoder is None:
        from ..encoders.registry import get_encoder
        sig_runs = [
            r for r in list_runs("features", runs_dir=runs_dir)
            if str(r.manifest["params"].get("encoder", "")).startswith("siglip2")
        ]
        if not sig_runs:
            raise RuntimeError("Aucun run SigLIP 2 trouvé pour encoder les requêtes.")
        p_sig = sig_runs[-1].manifest["params"]
        say(f"  Chargement de {p_sig['encoder']} pour encoder les requêtes…")
        encoder = get_encoder(p_sig["encoder"], hf_model=p_sig.get("weights"), input_size=p_sig.get("input_size"))

    cmap = center_bias_map(128)
    lmaps = {p.artwork_id: local_contrast_map(crop_painting(p), size=128) for p in matched}

    # --- Protocole 1 : requêtes iconographiques fixes
    q_vecs = np.asarray(encoder.encode_text(list(queries)), dtype=np.float32)
    q_vecs /= np.maximum(np.linalg.norm(q_vecs, axis=1, keepdims=True), 1e-12)

    raw_hits: list[dict] = []
    by_painting_hits: dict[int, list[dict]] = {}
    for q, qv in zip(queries, q_vecs):
        # On demande assez de voisines pour trouver top_k_per_query parmi les peintures AVAtt :
        # plutôt que d'élargir k sur 1,6 M zones (qui pourrait rater des peintures AVAtt),
        # on évalue exactement les 20 zones de chaque peinture AVAtt dans z_index.full si dispo,
        # sinon on passe par z_index.search(..., allowed=allowed).
        hits = _search_avatt_zones(z_index, qv, allowed, k=top_k_per_query)
        for rank_q, h in enumerate(hits, start=1):
            p = by_aid[h["id"]]
            ev = _eval_single_zone(p, h["grid"], h["box"], cmap, lmaps[p.artwork_id])
            rec = {
                "query": q,
                "rank_in_query": rank_q,
                "score": h["score"],
                "grid": h["grid"],
                "box": h["box"],
                "image_id": p.image_id,
                "artwork_id": p.artwork_id,
                "title": p.title,
                "artist": p.artist,
                **ev,
            }
            raw_hits.append(rec)
            by_painting_hits.setdefault(p.artwork_id, []).append(rec)

    # Agrégation par peinture pour le bootstrap sur les peintures
    painting_agg: list[dict] = []
    for aid, recs in sorted(by_painting_hits.items()):
        p = by_aid[aid]
        agg: dict = {"image_id": p.image_id, "artwork_id": aid, "n_queries": len(recs)}
        for cond in ("zone", "random", "center", "contrast"):
            agg[cond] = {
                m: float(np.mean([r[cond][m] for r in recs]))
                for m in ("fix_share", "area", "enrichment", "nss", "rank_pct")
            }
        painting_agg.append(agg)

    q_summary = _summarize_conditions(
        painting_agg,
        keys=("zone", "random", "center", "contrast"),
        metrics=("fix_share", "area", "enrichment", "nss", "rank_pct"),
        n_boot=n_boot,
        seed=seed,
    )
    q_summary["n_queries"] = len(queries)
    q_summary["top_k_per_query"] = top_k_per_query
    q_summary["n_hits"] = len(raw_hits)
    q_summary["grid_counts"] = {
        "2x2": sum(1 for r in raw_hits if r["grid"] == 2),
        "4x4": sum(1 for r in raw_hits if r["grid"] == 4),
    }
    q_summary["hits"] = raw_hits

    # --- Protocole 2 : titre propre de chaque peinture (lorsqu'il est renseigné)
    titled = [p for p in matched if p.title]
    title_records: list[dict] = []
    if titled:
        t_vecs = np.asarray(encoder.encode_text([p.title for p in titled]), dtype=np.float32)
        t_vecs /= np.maximum(np.linalg.norm(t_vecs, axis=1, keepdims=True), 1e-12)
        for p, tv in zip(titled, t_vecs):
            hits = _search_avatt_zones(z_index, tv, {p.artwork_id}, k=1)
            if not hits:
                continue
            h = hits[0]
            ev = _eval_single_zone(p, h["grid"], h["box"], cmap, lmaps[p.artwork_id])
            title_records.append({
                "query": p.title,
                "score": h["score"],
                "grid": h["grid"],
                "box": h["box"],
                "image_id": p.image_id,
                "artwork_id": p.artwork_id,
                "title": p.title,
                "artist": p.artist,
                **ev,
            })

    t_summary = _summarize_conditions(
        title_records,
        keys=("zone", "random", "center", "contrast"),
        metrics=("fix_share", "area", "enrichment", "nss", "rank_pct"),
        n_boot=n_boot,
        seed=seed + 1,
    )
    t_summary["grid_counts"] = {
        "2x2": sum(1 for r in title_records if r["grid"] == 2),
        "4x4": sum(1 for r in title_records if r["grid"] == 4),
    }
    t_summary["records"] = title_records

    say(
        f"  search_zones : {len(raw_hits)} zones sur {len(painting_agg)} peintures ({len(queries)} requêtes) "
        f"· titres : {len(title_records)} peintures"
    )
    return {
        "index_id": z_run.id,
        "iconographic_queries": q_summary,
        "title_queries": t_summary,
    }


def _search_avatt_zones(
    z_index: ZoneIndex,
    text_vec: np.ndarray,
    allowed: set[int],
    k: int = 15,
) -> list[dict]:
    """Meilleure zone par œuvre dans ``allowed`` pour ``text_vec`` (exact sur ``z_index.full`` si dispo)."""
    v = np.asarray(text_vec, dtype=np.float32)
    if z_index.full is not None and z_index.zone_rows is not None:
        # Sélectionne exactement toutes les lignes d'index appartenant à ``allowed``
        mask = np.isin(z_index.zone_ids, list(allowed))
        idx = np.flatnonzero(mask)
        if not len(idx):
            return []
        rows = z_index.zone_rows[idx]
        cells = z_index.zone_cells[idx].astype(np.int64)
        vecs = np.asarray(z_index.full[rows, cells], dtype=np.float32)
        scores = vecs @ v
        order = np.argsort(-scores)
        out, seen = [], set()
        for o in order.tolist():
            r = int(idx[o])
            aid = int(z_index.zone_ids[r])
            if aid in seen:
                continue
            seen.add(aid)
            g, box = z_index.boxes[int(z_index.zone_cells[r])]
            out.append({"id": aid, "score": round(float(scores[o]), 4), "grid": g, "box": list(box)})
            if len(out) >= k:
                break
        return out
    return z_index.search(v, k=k, allowed=allowed)


# ------------------------------------------------------------------ planches visuelles de contrôle
def _overlay_gaze_and_boxes(
    painting: AvattPainting,
    boxes: list[list[float]],
    *,
    thumb_w: int = 420,
    thumb_h: int = 320,
    caption: str = "",
) -> Image.Image:
    """Superpose la carte de chaleur humaine, les fixations et les cadres PixPlot."""
    crop = crop_painting(painting)
    cw, ch = crop.size
    scale = min(thumb_w / max(cw, 1), thumb_h / max(ch, 1))
    nw, nh = max(1, int(round(cw * scale))), max(1, int(round(ch * scale)))
    base = crop.resize((nw, nh), Image.Resampling.LANCZOS).convert("RGBA")

    # Carte de saillance humaine (depuis saliency_maps si disponible, sinon densité des fixations)
    if painting.saliency_path and painting.saliency_path.exists():
        with Image.open(painting.saliency_path) as sm:
            sal = sm.convert("L").crop(painting.painting_box).resize((nw, nh), Image.Resampling.BILINEAR)
        s_arr = np.asarray(sal, dtype=np.float32) / 255.0
    else:
        grid = np.zeros((nh, nw), dtype=np.float32)
        if len(painting.fixations):
            ix = np.clip((painting.fixations[:, 0] * nw).astype(np.int64), 0, nw - 1)
            iy = np.clip((painting.fixations[:, 1] * nh).astype(np.int64), 0, nh - 1)
            np.add.at(grid, (iy, ix), 1.0)
        s_im = Image.fromarray((grid / max(float(grid.max()), 1e-6) * 255).astype(np.uint8), mode="L")
        s_arr = np.asarray(s_im.filter(ImageFilter.GaussianBlur(radius=max(3, nw // 25))), dtype=np.float32) / 255.0
        if s_arr.max() > 0:
            s_arr /= s_arr.max()

    # Palette chaleur rouge-jaune semi-transparente
    heat = np.zeros((nh, nw, 4), dtype=np.uint8)
    heat[:, :, 0] = np.clip(s_arr * 2.0 * 255, 0, 255).astype(np.uint8)
    heat[:, :, 1] = np.clip((s_arr - 0.35) * 1.8 * 255, 0, 255).astype(np.uint8)
    heat[:, :, 2] = 0
    heat[:, :, 3] = np.clip(s_arr * 155, 0, 165).astype(np.uint8)
    comp = Image.alpha_composite(base, Image.fromarray(heat, mode="RGBA")).convert("RGB")

    draw = ImageDraw.Draw(comp)
    for idx, b in enumerate(boxes):
        col = PALETTE_BOXES[idx % len(PALETTE_BOXES)]
        x0, y0 = int(round(b[0] * nw)), int(round(b[1] * nh))
        x1, y1 = int(round(b[2] * nw)), int(round(b[3] * nh))
        draw.rectangle([x0, y0, max(x0 + 1, x1 - 1), max(y0 + 1, y1 - 1)], outline=col, width=3)
        draw.rectangle([x0, y0, x0 + 18, y0 + 16], fill=col)
        draw.text((x0 + 5, y0 + 2), str(idx + 1), fill=(15, 15, 15))

    pad_bottom = 44
    tile = Image.new("RGB", (thumb_w, thumb_h + pad_bottom), (24, 24, 28))
    ox, oy = (thumb_w - nw) // 2, (thumb_h - nh) // 2
    tile.paste(comp, (ox, oy))
    tdraw = ImageDraw.Draw(tile)
    for li, line in enumerate(caption.splitlines()[:2]):
        tdraw.text((8, thumb_h + 6 + li * 16), line[:62], fill=(235, 235, 240))
    return tile


def render_contact_sheet(
    items: list[tuple[AvattPainting, list[list[float]], str]],
    out_path: Path,
    cols: int = 3,
) -> Path:
    """Assemble une planche contact d'exemples superposés (fixations + cadres PixPlot)."""
    if not items:
        return out_path
    tiles = [_overlay_gaze_and_boxes(p, b, caption=cap) for p, b, cap in items]
    tw, th = tiles[0].size
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, rows * th), (18, 18, 22))
    for i, t in enumerate(tiles):
        r, c = divmod(i, cols)
        sheet.paste(t, (c * tw, r * th))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, quality=90)
    return out_path


# ------------------------------------------------------------------ exécution complète
def run_oculometrie(
    avatt_dir: Path,
    catalog_path: Path,
    runs_dir: Path,
    out_dir: Path,
    *,
    n_boot: int = 2000,
    seed: int = 0,
    skip_zones: bool = False,
    say: Callable[[str], None] = print,
) -> dict:
    """Exécute le rattachement AVAtt, les mesures (a), (b), (c) et génère les planches visuelles."""
    say("1. Chargement d'AVAtt…")
    paintings, load_info = load_avatt(avatt_dir)
    say(f"   {load_info['paintings_loaded']} peintures uniques ({load_info['duplicates_excluded']} doublon exclu), "
        f"{load_info['fixations_in_painting']}/{load_info['fixations_raw']} fixations dans la peinture ({load_info['fixations_in_ratio']:.2%}).")

    say("2. Rattachement au catalogue par dHash…")
    match_info = match_avatt_to_catalog(paintings, catalog_path)
    say(f"   {match_info['matched']}/{match_info['total']} rattachées ({match_info['unmatched']} absentes, "
        f"{match_info['rejected_margin']} rejetées par marge).")

    say("3. Mesure (a) & (c) : zones du « Pourquoi ? » (AVAtt ↔ AVAtt et AVAtt ↔ corpus)…")
    why_avatt = evaluate_why(paintings, catalog_path, runs_dir, neighbor_pool="avatt", n_boot=n_boot, seed=seed, say=say)
    why_corpus = evaluate_why(paintings, catalog_path, runs_dir, neighbor_pool="corpus", n_boot=n_boot, seed=seed + 10, say=say)

    zones_res = None
    if not skip_zones and find_zone_index(runs_dir) is not None:
        say("4. Mesure (b) & (c) : zones de `search_zones`…")
        zones_res = evaluate_search_zones(paintings, runs_dir, n_boot=n_boot, seed=seed + 20, say=say)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    by_id = {p.image_id: p for p in paintings}

    # Planches visuelles : 3 réussites + 3 échecs pour « Pourquoi ? » et pour `search_zones`
    sheets: dict[str, str] = {}
    if why_avatt["records"]:
        recs = sorted(why_avatt["records"], key=lambda r: r["why"]["nss"], reverse=True)
        pick = recs[:3] + recs[-3:]
        items = [
            (
                by_id[r["image_id"]],
                r["why_boxes"],
                f"{r['image_id']} · {(r['title'] or r['artist'] or 'sans titre')[:32]}\n"
                f"fix {r['why']['fix_share']:.0%} (surf {r['why']['area']:.0%}) · NSS {r['why']['nss']:+.2f} · cos {r['neighbor_cos']:.2f}",
            )
            for r in pick
        ]
        p_sheet = render_contact_sheet(items, out_dir / "planche_pourquoi.jpg", cols=3)
        sheets["why"] = str(p_sheet)

    if zones_res and zones_res["iconographic_queries"]["hits"]:
        hits = sorted(zones_res["iconographic_queries"]["hits"], key=lambda r: r["zone"]["nss"], reverse=True)
        # 3 réussites et 3 échecs sur des peintures distinctes
        top_h, bot_h, seen_p = [], [], set()
        for h in hits:
            if h["image_id"] not in seen_p:
                top_h.append(h)
                seen_p.add(h["image_id"])
            if len(top_h) == 3:
                break
        for h in reversed(hits):
            if h["image_id"] not in seen_p:
                bot_h.append(h)
                seen_p.add(h["image_id"])
            if len(bot_h) == 3:
                break
        items_z = [
            (
                by_id[r["image_id"]],
                [r["box"]],
                f"« {r['query']} » ({r['grid']}x{r['grid']}) · {r['image_id']}\n"
                f"fix {r['zone']['fix_share']:.0%} (surf {r['zone']['area']:.0%}) · NSS {r['zone']['nss']:+.2f} · rang {r['zone']['rank_pct']:.0%}",
            )
            for r in (top_h + bot_h)
        ]
        p_zsheet = render_contact_sheet(items_z, out_dir / "planche_search_zones.jpg", cols=3)
        sheets["search_zones"] = str(p_zsheet)

    report = {
        "avatt": load_info,
        "matching": match_info,
        "why_avatt": why_avatt,
        "why_corpus": why_corpus,
        "search_zones": zones_res,
        "sheets": sheets,
    }
    report_path = out_dir / "oculometrie_report.json"
    report_path.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    say(f"Rapport écrit : {report_path}")
    return report
