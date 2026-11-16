"""Analyse d'un run de vecteurs : groupes, carte 2D, voisinages, œuvres atypiques.

Contenu d'un run ``analysis/<encodeur>_<horodatage>/`` :

    manifest.json        paramètres (nombre de groupes, UMAP...), run parent
    ids.npy              (N,)      identifiants catalogue, ordre des lignes
    coords.npy           (N, 2)    position sur la carte, dans [-1, 1]
    clusters.npy         (N,)      groupe e-means de chaque œuvre
    centroids.npy        (K, D)    centres des groupes (normalisés)
    clusters.json        par groupe : taille, œuvre représentative (la plus proche du centre)
    hdbscan.npy          (N,)      groupe HDBSCAN, -1 = œuvre « à part » (option)
    neighbors.npy        (N, k)    identifiants des k plus proches voisines
    neighbor_scores.npy  (N, k)    similarités correspondantes
    atypicality.npy      (N,)      0 = très entourée … 1 = très isolée

Toutes les étapes ont une graine fixe : relancer avec les mêmes paramètres redonne
le même résultat (principe de reproductibilité).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Callable

import numpy as np

from ..features.extract import OK
from ..runs import Run, create_run

SEED = 42


def default_cluster_count(n: int) -> int:
    """≈ √N / 2, entre 8 et 200 : assez de groupes pour explorer, pas trop pour un menu."""
    return int(min(200, max(8, round(math.sqrt(n) / 2))))


def load_valid(features: Run) -> tuple[np.ndarray, np.ndarray]:
    p = Path(features.path)
    keep = np.load(p / "status.npy") == OK
    ids = np.load(p / "ids.npy")[keep]
    X = np.ascontiguousarray(np.load(p / "global.npy", mmap_mode="r")[keep], dtype=np.float32)
    X /= np.maximum(np.linalg.norm(X, axis=1, keepdims=True), 1e-12)
    return ids, X


def cluster_emeans(X: np.ndarray, k: int, epochs: float = 5) -> tuple[np.ndarray, np.ndarray]:
    """Regroupement e-means sphérique (Meta FAIR, FAISS ≥ 1.16). Renvoie (labels, centres)."""
    from faiss.contrib.e_means import NumpyEmeans

    model = NumpyEmeans(X.shape[1], k, nepochs=epochs, seed=SEED, spherical=True)
    model.train(X)
    _, labels = model.assign(X)  # affectation finale, sur les centres définitifs
    centroids = np.asarray(model.centroids, dtype=np.float32)
    centroids /= np.maximum(np.linalg.norm(centroids, axis=1, keepdims=True), 1e-12)
    return labels.astype(np.int32), centroids


def reduce_pca(X: np.ndarray, dims: int = 64) -> np.ndarray:
    from sklearn.decomposition import PCA

    dims = min(dims, X.shape[1], len(X) - 1)
    return PCA(n_components=dims, random_state=SEED).fit_transform(X).astype(np.float32)


def run_umap(Z: np.ndarray, n_components: int = 2, n_neighbors: int = 15, min_dist: float = 0.1,
             fit_sample: int = 100_000) -> np.ndarray:
    """UMAP. Au-delà de ``fit_sample`` œuvres, apprend sur un échantillon puis place le
    reste (tient dans 16 Go de RAM pour 500 000 œuvres)."""
    import umap

    kwargs = {}
    if "compatibility_layout" in umap.UMAP.__init__.__code__.co_varnames:
        # umap-learn ≥ 0.6 annonce un changement d'algorithme par défaut : on fige l'actuel
        # pour que la même analyse redonne la même carte (reproductibilité).
        kwargs["compatibility_layout"] = True
    reducer = umap.UMAP(n_neighbors=n_neighbors, min_dist=min_dist, metric="euclidean",
                        random_state=SEED, n_components=n_components, **kwargs)
    if len(Z) <= fit_sample:
        return np.asarray(reducer.fit_transform(Z), dtype=np.float32)
    rng = np.random.default_rng(SEED)
    reducer.fit(Z[rng.choice(len(Z), fit_sample, replace=False)])
    out = np.empty((len(Z), n_components), dtype=np.float32)
    for s in range(0, len(Z), 50_000):
        out[s:s + 50_000] = reducer.transform(Z[s:s + 50_000])
    return out


def layout_umap(Z: np.ndarray, n_neighbors: int = 15, min_dist: float = 0.1) -> np.ndarray:
    """Carte 2D, normalisée dans [-1, 1]."""
    return normalize_coords(run_umap(Z, 2, n_neighbors, min_dist))


def normalize_coords(c: np.ndarray, clip_percent: float = 0.5) -> np.ndarray:
    """Centre la carte et la ramène dans [-1, 1] en gardant les proportions.

    L'échelle ignore les ``clip_percent`` % d'œuvres les plus excentrées de chaque côté
    (sinon quelques isolées tout au bord écrasent le reste de la carte) ; ces œuvres-là
    sont posées sur le bord. Elles restent repérables par leur score d'atypicité."""
    lo = np.percentile(c, clip_percent, axis=0)
    hi = np.percentile(c, 100 - clip_percent, axis=0)
    c = c - (lo + hi) / 2
    scale = max(float(np.max((hi - lo) / 2)), 1e-12)
    return np.clip(c / scale, -1, 1).astype(np.float32)


def neighbors(X: np.ndarray, k: int = 20) -> tuple[np.ndarray, np.ndarray]:
    """k plus proches voisines de chaque œuvre (indices de lignes, soi-même exclu)."""
    import faiss

    index = faiss.IndexFlatIP(X.shape[1])
    index.add(X)
    scores, rows = index.search(X, k + 1)
    out_rows = np.empty((len(X), k), dtype=np.int64)
    out_scores = np.empty((len(X), k), dtype=np.float32)
    for i in range(len(X)):
        keep = rows[i] != i
        r, s = rows[i][keep][:k], scores[i][keep][:k]
        out_rows[i, :len(r)], out_scores[i, :len(s)] = r, s
        out_rows[i, len(r):], out_scores[i, len(s):] = -1, 0
    return out_rows, out_scores


def atypicality(neighbor_scores: np.ndarray) -> np.ndarray:
    """Isolement d'une œuvre : faible similarité moyenne avec ses voisines → score élevé.
    Rang centile dans [0, 1] : comparable d'un modèle ou d'un corpus à l'autre."""
    density = neighbor_scores.mean(axis=1)
    order = np.argsort(np.argsort(density))
    return (1.0 - order / max(len(order) - 1, 1)).astype(np.float32)


def hdbscan_sizes(n: int) -> tuple[int, int]:
    """(min_cluster_size, min_samples). Sur WikiArt 2 263 œuvres : 7 familles, 1,6 % à part.

    Limite connue : sur un continuum dense (WikiArt 80 716 œuvres), aucun réglage n'est
    exploitable — mcs=40 : 261 micro-familles et 53 % « à part » ; mcs≥100 : un bloc de
    70 % du corpus et 0,2 % à part. À grande échelle, se fier au score d'atypicité."""
    return max(15, n // 2000), 5


def cluster_hdbscan(Z: np.ndarray, min_cluster_size: int | None = None,
                    min_samples: int | None = None) -> np.ndarray:
    """HDBSCAN sur une UMAP intermédiaire en 10 dimensions (directement sur les vecteurs, la
    densité est trop uniforme et presque tout est déclaré « à part »)."""
    from sklearn.cluster import HDBSCAN

    mcs, ms = hdbscan_sizes(len(Z))
    U = run_umap(Z, n_components=10, min_dist=0.0)
    return HDBSCAN(min_cluster_size=min_cluster_size or mcs, min_samples=min_samples or ms,
                   copy=True).fit_predict(U).astype(np.int32)


def analyze(
    features: Run,
    runs_dir: Path | None = None,
    n_clusters: int | None = None,
    use_hdbscan: bool = False,
    n_neighbors: int = 20,
    umap_neighbors: int = 15,
    umap_min_dist: float = 0.1,
    pca_dims: int = 64,
    progress: Callable[[str], None] | None = None,
) -> Run:
    say = progress or (lambda msg: None)
    ids, X = load_valid(features)
    if len(ids) < 10:
        raise RuntimeError("Il faut au moins 10 œuvres pour une analyse.")
    k = n_clusters or default_cluster_count(len(ids))
    params = {"clusters": k, "cluster_method": "e-means (sphérique)", "hdbscan": use_hdbscan,
              "neighbors": n_neighbors, "pca_dims": pca_dims, "umap_neighbors": umap_neighbors,
              "umap_min_dist": umap_min_dist, "seed": SEED}
    run = create_run("analysis", features.manifest["name"], params, parent=features, runs_dir=runs_dir)
    p = run.path
    try:
        np.save(p / "ids.npy", ids)

        say(f"Regroupement e-means en {k} groupes…")
        labels, centroids = cluster_emeans(X, k)
        np.save(p / "clusters.npy", labels)
        np.save(p / "centroids.npy", centroids)
        sims = X @ centroids.T
        summary = []
        for c in range(k):
            members = np.flatnonzero(labels == c)
            if not len(members):
                continue
            rep = members[np.argmax(sims[members, c])]
            summary.append({"cluster": c, "size": int(len(members)), "representative": int(ids[rep]),
                            "label": f"Groupe {c + 1}"})
        summary.sort(key=lambda d: -d["size"])
        (p / "clusters.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")

        say(f"Voisinages ({n_neighbors} plus proches)…")
        nn_rows, nn_scores = neighbors(X, n_neighbors)
        np.save(p / "neighbors.npy", np.where(nn_rows >= 0, ids[np.clip(nn_rows, 0, None)], -1))
        np.save(p / "neighbor_scores.npy", nn_scores)
        np.save(p / "atypicality.npy", atypicality(nn_scores))

        say(f"Réduction PCA à {pca_dims} dimensions, puis carte UMAP…")
        Z = reduce_pca(X, pca_dims)
        np.save(p / "coords.npy", layout_umap(Z, umap_neighbors, umap_min_dist))

        if use_hdbscan:
            say("HDBSCAN (œuvres « à part »)…")
            h = cluster_hdbscan(Z)
            np.save(p / "hdbscan.npy", h)
    except BaseException as exc:
        run.fail(exc)
        raise

    out = {"count": int(len(ids)), "clusters": len(summary)}
    if use_hdbscan:
        out.update(hdbscan_clusters=int(h.max() + 1), hdbscan_isolated=int((h < 0).sum()))
    run.complete(**out)
    return run
