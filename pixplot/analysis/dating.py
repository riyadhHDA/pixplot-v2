"""Dater une œuvre d'après ses voisines datées, avec une fourchette calibrée.

Idée (d'après Schneider et al., « Uncertainty-Aware Art-Historical Dating with Vision-Language Models »,
arXiv 2608.18984, 2026, qui régressent la date depuis des vecteurs figés) : dans un regard, on prend les ``k``
plus proches voisines **datées** d'une œuvre ; la date estimée est la médiane de leurs années, pondérée par la
ressemblance ; la fourchette est l'écart entre deux quantiles pondérés (10 % et 90 %), élargie par une
calibration « conforme » sur des œuvres datées mises de côté, pour que la fourchette annoncée à 80 % contienne
vraiment la date dans 80 % des cas.

Garde-fous mesurés :

- l'œuvre elle-même et ses doublons (même image entrée deux fois, ``doublons.json``) ne comptent jamais ;
- mode « artiste caché » : aucune voisine du même artiste ; sinon dater revient en partie à reconnaître
  l'artiste, ce qui est utile pour une œuvre d'artiste connu mais gonfle la mesure ;
- témoins : l'année médiane du style de l'œuvre (métadonnées) et la médiane du corpus.

Une date estimée est une piste, pas une datation : elle dit à quelle période ressemblent les œuvres voisines.
Deux méthodes, mesurées sur WikiArt 81k (ARCHITECTURE § 45) : si l'artiste a au moins ``MIN_ARTIST_DATED``
autres œuvres datées, seules celles-ci servent (l'œuvre se place dans la chronologie de son artiste) ; sinon,
toutes les voisines datées, avec une fourchette calibrée comme si l'artiste était inconnu.

Sortie : ``datation.npy`` (N, 5) dans le run d'analyse, aligné sur ``ids.npy`` : année estimée, bas et haut de
la fourchette à 80 %, nombre de voisines datées utilisées, méthode (1 = même artiste, 2 = toutes les voisines) ;
NaN si aucune voisine datée.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

FILE = "datation.npy"
COVERAGE = 0.8
MIN_ARTIST_DATED = 5     # au-delà, on date une œuvre d'après les seules œuvres datées de son artiste


def neighbor_years(X: np.ndarray, years: np.ndarray, dated: np.ndarray, k: int = 20,
                   artists: np.ndarray | None = None, exclude: dict[int, set[int]] | None = None,
                   block: int = 1024, tau: float = 0.03, rows: np.ndarray | None = None,
                   same_artist_only: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """Années et poids des ``k`` plus proches voisines datées des lignes ``rows`` de ``X`` (toutes par défaut ;
    vecteurs normalisés).

    ``dated`` : masque des lignes datées. ``artists`` : si donné, les voisines du même artiste sont écartées
    (codes entiers, -1 = artiste inconnu, jamais écarté). ``exclude`` : lignes à écarter pour une ligne donnée
    (doublons). Poids : ``exp((s - s_max) / tau)``. Renvoie deux tableaux (len(rows), k), NaN là où il manque
    des voisines.
    """
    rows = np.arange(len(X)) if rows is None else np.asarray(rows)
    n = len(rows)
    D = np.flatnonzero(dated)
    XD = X[D]
    yD = years[D].astype(np.float64)
    aD = artists[D] if artists is not None else None
    pos = {int(r): j for j, r in enumerate(D)} if exclude else {}
    Y = np.full((n, k), np.nan)
    Wt = np.zeros((n, k))
    for s in range(0, n, block):
        out_i = np.arange(s, min(s + block, n))
        q = rows[out_i]
        S = X[q] @ XD.T
        S[np.equal.outer(q, D)] = -np.inf                          # l'œuvre elle-même
        if aD is not None:
            aq = artists[q]
            same = (aq[:, None] == aD[None, :]) & (aq[:, None] >= 0)
            if same_artist_only:
                # seulement les œuvres datées du même artiste (artiste inconnu : pas de restriction)
                S[~same & (aq[:, None] >= 0)] = -np.inf
            else:
                S[same] = -np.inf
        if exclude:
            for i, r in enumerate(q):
                for o in exclude.get(int(r), ()):
                    j = pos.get(o)
                    if j is not None:
                        S[i, j] = -np.inf
        kk = min(k, S.shape[1])
        top = np.argpartition(-S, kk - 1, axis=1)[:, :kk]
        st = np.take_along_axis(S, top, axis=1)
        order = np.argsort(-st, axis=1)
        top, st = np.take_along_axis(top, order, axis=1), np.take_along_axis(st, order, axis=1)
        ok = np.isfinite(st)
        w = np.where(ok, np.exp((st - st[:, :1]) / tau), 0.0)
        Y[out_i, :kk] = np.where(ok, yD[top], np.nan)
        Wt[out_i, :kk] = w
    return Y, Wt


def weighted_quantiles(Y: np.ndarray, W: np.ndarray, qs: tuple[float, ...]) -> np.ndarray:
    """Quantiles pondérés ligne à ligne (NaN si aucune année). Renvoie (N, len(qs))."""
    out = np.full((len(Y), len(qs)), np.nan)
    for i in range(len(Y)):
        m = np.isfinite(Y[i]) & (W[i] > 0)
        if not m.any():
            continue
        y, w = Y[i][m], W[i][m]
        o = np.argsort(y)
        y, c = y[o], np.cumsum(w[o]) / w[o].sum()
        out[i] = [y[min(np.searchsorted(c, q), len(y) - 1)] for q in qs]
    return out


def conformal_margin(lo: np.ndarray, hi: np.ndarray, y: np.ndarray, coverage: float = COVERAGE) -> float:
    """Marge à ajouter aux deux bords pour qu'une fourchette [lo, hi] contienne ``y`` avec la couverture voulue
    (calibration conforme des quantiles : quantile des dépassements, corrigé pour la taille de l'échantillon)."""
    e = np.maximum(lo - y, y - hi)
    e = e[np.isfinite(e)]
    if not len(e):
        return 0.0
    level = min(1.0, np.ceil((len(e) + 1) * coverage) / len(e))
    return float(np.quantile(e, level))


def estimate(Y: np.ndarray, W: np.ndarray, margin: float = 0.0) -> np.ndarray:
    """(N, 4) : année estimée (médiane pondérée), bas, haut (quantiles 10 % / 90 % élargis de ``margin``),
    nombre de voisines datées."""
    q = weighted_quantiles(Y, W, (0.1, 0.5, 0.9))
    n = np.isfinite(Y).sum(axis=1).astype(float)
    out = np.column_stack([q[:, 1], q[:, 0] - margin, q[:, 2] + margin, n])
    out[n == 0] = np.nan
    return out


def evaluate(est_lo_hi: np.ndarray, y: np.ndarray, calib: np.ndarray, test: np.ndarray) -> dict:
    """Calibre la marge sur ``calib`` et mesure sur ``test`` : erreur absolue médiane, part à ±25 ans,
    couverture et largeur médiane de la fourchette."""
    pred, lo, hi = est_lo_hi[:, 0], est_lo_hi[:, 1], est_lo_hi[:, 2]
    margin = conformal_margin(lo[calib], hi[calib], y[calib])
    lo2, hi2 = lo - margin, hi + margin
    t = test & np.isfinite(pred)
    err = np.abs(pred[t] - y[t])
    return {"n_test": int(t.sum()), "erreur_mediane": round(float(np.median(err)), 1),
            "erreur_moyenne": round(float(np.mean(err)), 1),
            "a_25_ans": round(float(np.mean(err <= 25)), 3),
            "marge_conforme": round(margin, 1),
            "couverture": round(float(np.mean((y[t] >= lo2[t]) & (y[t] <= hi2[t]))), 3),
            "largeur_mediane": round(float(np.median(hi2[t] - lo2[t])), 1)}


def baseline_style(styles: list[str], y: np.ndarray, dated: np.ndarray, calib: np.ndarray, test: np.ndarray) -> dict:
    """Témoin : l'année médiane des œuvres datées du même style (calculée sans les œuvres de test)."""
    ref = dated & ~test
    st = np.array(styles)
    glob = float(np.median(y[ref]))
    q: dict[str, tuple[float, float, float]] = {}
    for s in set(styles):
        m = ref & (st == s)
        if m.any():
            q[s] = tuple(float(v) for v in np.quantile(y[m], (0.5, 0.1, 0.9)))
    arr = np.array([q.get(s, (glob, glob, glob)) for s in styles], dtype=float)
    return evaluate(arr, y, calib, test)


def baseline_global(y: np.ndarray, dated: np.ndarray, calib: np.ndarray, test: np.ndarray) -> dict:
    """Témoin : la même année pour toutes (médiane du corpus daté, sans les œuvres de test)."""
    ref = dated & ~test
    m, lo, hi = np.quantile(y[ref], (0.5, 0.1, 0.9))
    arr = np.tile([m, lo, hi], (len(y), 1)).astype(float)
    return evaluate(arr, y, calib, test)


def save(analysis, arr: np.ndarray, meta: dict) -> Path:
    path = Path(analysis.path) / FILE
    np.save(path, arr.astype(np.float32))
    path.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load(analysis) -> tuple[np.ndarray, dict] | None:
    path = Path(analysis.path) / FILE
    if not path.exists():
        return None
    meta_path = path.with_suffix(".json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    return np.load(path), meta
