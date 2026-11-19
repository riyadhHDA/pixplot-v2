"""Mesures visuelles explicites d'après D. G. Stork, *Pixels & Paintings: Foundations of
Computer-assisted Connoisseurship* (Wiley, 2024).

Ces mesures sont calculées directement sur les pixels, sans modèle de neurones et sans GPU, en
quelques millisecondes par œuvre. Elles ne portent aucun jugement normatif (une composition
équilibrée ou symétrique n'est pas « meilleure » qu'une autre) et portent toujours sur la
*reproduction numérique* (exposition, vernis, scan), non sur l'œuvre matérielle :

- **Équilibre visuel (barycentre)** (§ 9.3, éqs. 9.1–9.2, d'après Arnheim, Gombrich et Park 2019) :
  centre de masse de la luminance et de la saturation, plus dispersion des barycentres locaux
  (faible sur un *all-over* homogène, forte sur une composition focalisée).
- **Symétrie gauche-droite** (§ 9.3) : corrélation de luminance avec l'image retournée en miroir.
- **Entropie chromatique et première coupe** (§ 9.5.1, éqs. 9.3–9.5, algorithme 8, d'après Lee et
  al., PNAS 2020) : diversité des couleurs en bits et droite horizontale ou verticale qui sépare le
  mieux deux zones chromatiquement distinctes (par ex. la ligne d'horizon d'un paysage).
- **Dynamique tonale** (§ 1.5.3) : clarté moyenne, étendue p5–p95 et part de tons sombres.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image


NOTE = (
    "Mesures calculées sur la reproduction numérique (non sur l'œuvre matérielle), sans jugement "
    "normatif : une composition équilibrée ou symétrique n'est pas meilleure qu'une autre "
    "(D. G. Stork, Pixels & Paintings, 2024)."
)


def _barycenter(weights: np.ndarray) -> tuple[float, float]:
    """Centre de masse normalisé ``(x, y)`` dans ``[0, 1] × [0, 1]`` (haut-gauche = ``(0, 0)``)."""
    h, w = weights.shape
    total = float(weights.sum())
    if total <= 1e-12 or h == 0 or w == 0:
        return 0.5, 0.5
    xs = (np.arange(w, dtype=np.float64) + 0.5) / w
    ys = (np.arange(h, dtype=np.float64) + 0.5) / h
    xc = float((weights.sum(axis=0) * xs).sum() / total)
    yc = float((weights.sum(axis=1) * ys).sum() / total)
    return xc, yc


def _subset_barycenter_spread(lum: np.ndarray, grid: int = 5) -> float:
    """Dispersion (écart-type radial) des barycentres de sous-fenêtres de même proportion.

    D'après Stork § 9.3 (fig. 9.2, Park 2019) : faible sur une surface homogène (*all-over*
    type Pollock), plus élevée lorsque le poids visuel se concentre dans certaines zones.
    """
    h, w = lum.shape
    wh, ww = max(4, h // 2), max(4, w // 2)
    if h <= wh or w <= ww:
        return 0.0
    ys = np.linspace(0, h - wh, grid, dtype=int)
    xs = np.linspace(0, w - ww, grid, dtype=int)
    pts = [_barycenter(lum[y:y + wh, x:x + ww]) for y in ys for x in xs]
    arr = np.asarray(pts, dtype=np.float64)
    centered = arr - arr.mean(axis=0)
    return float(np.sqrt(np.mean(np.sum(centered * centered, axis=1))))


def _shannon_entropy(counts: np.ndarray) -> float:
    total = float(counts.sum())
    if total <= 0:
        return 0.0
    p = counts[counts > 0] / total
    return float(-(p * np.log2(p)).sum())


def _chromatic_split(im: Image.Image, levels: int = 4, max_side: int = 96) -> dict:
    """Entropie chromatique H(C) et première coupe horizontale ou verticale (Stork § 9.5.1, alg. 8).

    Utilise une grille chromatique fixe ``levels × levels × levels`` (64 teintes pour ``levels=4``,
    max 6 bits) plutôt qu'une quantification adaptative : l'entropie reste ainsi directement
    comparable d'une œuvre à l'autre (monochrome ≈ 0 bit, grisaille ≈ 1–2 bits, polychrome ≈ 4–5 bits).
    """
    n_colors = levels ** 3
    small = im.copy()
    small.thumbnail((max_side, max_side), Image.Resampling.BILINEAR)
    arr = np.asarray(small, dtype=np.uint16)
    bins = np.minimum(arr * levels // 256, levels - 1)
    q = (bins[..., 0] * (levels * levels) + bins[..., 1] * levels + bins[..., 2]).astype(np.int32)
    h, w = q.shape
    n_pix = h * w
    hist_all = np.bincount(q.ravel(), minlength=n_colors).astype(np.float64)
    h_total = _shannon_entropy(hist_all)

    def best_along(axis: int) -> tuple[float, float]:
        # axis=0 : coupe horizontale (sur y) ; axis=1 : coupe verticale (sur x)
        length = h if axis == 0 else w
        lo, hi = max(1, int(round(length * 0.1))), min(length - 1, int(round(length * 0.9)))
        if hi <= lo:
            return 0.5, 0.0
        slices = np.zeros((length, n_colors), dtype=np.float64)
        for i in range(length):
            line = q[i, :] if axis == 0 else q[:, i]
            slices[i] = np.bincount(line, minlength=n_colors)
        cum = np.cumsum(slices, axis=0)
        best_pos, best_gain = 0.5, -1.0
        for cut in range(lo, hi):
            c1 = cum[cut - 1]
            c2 = hist_all - c1
            n1 = c1.sum()
            n2 = n_pix - n1
            if n1 <= 0 or n2 <= 0:
                continue
            h_cond = (n1 / n_pix) * _shannon_entropy(c1) + (n2 / n_pix) * _shannon_entropy(c2)
            gain = max(0.0, h_total - h_cond)
            if gain > best_gain:
                best_gain = gain
                best_pos = cut / length
        return best_pos, max(0.0, best_gain)

    y_pos, y_gain = best_along(0)
    x_pos, x_gain = best_along(1)
    if y_gain >= x_gain:
        orientation, pos, gain = "horizontale", y_pos, y_gain
    else:
        orientation, pos, gain = "verticale", x_pos, x_gain
    return {
        "entropy_bits": round(h_total, 3),
        "max_bits": round(float(np.log2(n_colors)), 3),
        "split_orientation": orientation,
        "split_position": round(pos, 3),
        "split_gain_bits": round(gain, 3),
        "split_ratio": round(gain / h_total, 3) if h_total > 1e-6 else 0.0,
    }


_N_PATTERNS = 24                                   # 4 ! ordres possibles des 4 pixels d'une fenêtre 2 × 2


def entropy_complexity(lum: np.ndarray) -> tuple[float, float]:
    """Entropie de permutation H et complexité statistique C d'une image en niveaux de gris
    (Sigaki, Perc et Ribeiro, *PNAS* 2018, d'après Bandt et Pompe).

    Chaque fenêtre 2 × 2 de pixels est réduite à l'**ordre** de ses quatre valeurs (24 ordres
    possibles, égalités départagées par la position). H (0 à 1) dit si ces ordres sont répartis au
    hasard (1 : bruit, matière désordonnée) ou concentrés sur quelques-uns (près de 0 : aplats,
    dégradés réguliers). C (0 à ~0,5) est forte entre les deux extrêmes : un ordre structuré mais
    non trivial. Dans l'article, les œuvres récentes vont vers plus de H et moins de C."""
    lum = np.asarray(lum, dtype=np.float64)
    if lum.ndim != 2 or min(lum.shape) < 2:
        return 0.0, 0.0
    win = np.stack([lum[:-1, :-1], lum[:-1, 1:], lum[1:, :-1], lum[1:, 1:]], axis=-1).reshape(-1, 4)
    ranks = np.argsort(win, axis=1, kind="stable")
    codes = ranks[:, 0] * 64 + ranks[:, 1] * 16 + ranks[:, 2] * 4 + ranks[:, 3]
    counts = np.bincount(codes, minlength=256).astype(np.float64)
    p = counts[counts > 0] / counts.sum()
    n = _N_PATTERNS
    s_p = float(-(p * np.log(p)).sum())
    h = s_p / np.log(n)
    full = np.zeros(n)
    full[:len(p)] = p                                   # l'ordre des cases n'importe pas ici
    mix = (full + 1.0 / n) / 2
    s_mix = float(-(mix[mix > 0] * np.log(mix[mix > 0])).sum())
    js = s_mix - s_p / 2 - np.log(n) / 2                # divergence de Jensen-Shannon avec l'uniforme
    q0 = -2.0 / (((n + 1) / n) * np.log(n + 1) - 2 * np.log(2 * n) + np.log(n))
    return float(abs(h)), float(abs(q0 * js * h))


def measure_image(im: Image.Image, max_side: int = 256) -> dict:
    """Calcule les mesures visuelles de Stork (2024) sur une image PIL."""
    rgb = im.convert("RGB")
    orig_w, orig_h = rgb.size
    work = rgb.copy()
    work.thumbnail((max_side, max_side), Image.Resampling.BILINEAR)
    arr = np.asarray(work, dtype=np.float32) / 255.0

    # Luminance relative sRGB et saturation HSV
    lum = 0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]
    cmax = arr.max(axis=2)
    cmin = arr.min(axis=2)
    sat = np.where(cmax > 1e-6, (cmax - cmin) / np.maximum(cmax, 1e-6), 0.0)

    # Équilibre visuel (barycentre global et dispersion locale)
    lx, ly = _barycenter(lum)
    sx, sy = _barycenter(sat)
    offset = float(np.hypot(lx - 0.5, ly - 0.5))
    spread = _subset_barycenter_spread(lum)

    # Symétrie gauche-droite (corrélation de Pearson entre l'image et son miroir)
    flat = lum.ravel().astype(np.float64)
    mir = lum[:, ::-1].ravel().astype(np.float64)
    denom = float(flat.std() * mir.std())
    sym = float(np.mean((flat - flat.mean()) * (mir - mir.mean())) / denom) if denom > 1e-9 else 1.0

    # Dynamique tonale (clarté, contraste p5–p95, part sombre)
    p5, p50, p95 = np.percentile(lum, [5, 50, 95])
    dark_share = float(np.mean(lum < 0.2))

    # Entropie chromatique et première coupe compositionnelle
    chroma = _chromatic_split(rgb)

    # Ordre et désordre de la matière (Sigaki, Perc et Ribeiro, 2018)
    h_perm, c_perm = entropy_complexity(lum)

    return {
        "aspect_ratio": round(orig_w / max(orig_h, 1), 3),
        "balance": {
            "lightness": [round(lx, 3), round(ly, 3)],
            "saturation": [round(sx, 3), round(sy, 3)],
            "center_offset": round(offset, 3),
            "local_spread": round(spread, 3),
        },
        "symmetry_lr": round(sym, 3),
        "tone": {
            "mean_lightness": round(float(lum.mean()), 3),
            "median_lightness": round(float(p50), 3),
            "contrast_p5_p95": round(float(p95 - p5), 3),
            "dark_share": round(dark_share, 3),
        },
        "chromatic": chroma,
        "order": {"permutation_entropy": round(h_perm, 3), "complexity": round(c_perm, 3)},
        "note": NOTE,
    }


def measure_path(path: Path) -> dict:
    """Ouvre un fichier image (vignette ou original) et calcule ses mesures visuelles."""
    with Image.open(path) as im:
        return measure_image(im)
