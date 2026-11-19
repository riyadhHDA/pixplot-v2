"""Groupes Leiden : emboîtés, réglables, un jeu par regard.

Pourquoi : e-means coupe l'espace en k cellules, avec k = √N / 2 fixé d'avance. Sur un
continuum sans vides (WikiArt), HDBSCAN échoue faute de creux de densité. Leiden travaille
sur le **graphe des voisines** (chaque œuvre reliée à ses k plus proches, pondéré par la
similarité) et cherche des communautés : des ensembles d'œuvres plus liées entre elles
qu'avec le reste. Le nombre de groupes devient un réglage (la résolution γ), et les groupes
sont connexes par construction.

Deux niveaux emboîtés :

- **groupes** (≈ autant qu'e-means, pour comparer à armes égales) ;
- **familles** : Leiden appliqué au graphe des groupes eux-mêmes, si bien qu'une famille est
  toujours une réunion de groupes (vue d'ensemble dans l'Atlas, détail au zoom).

Rien ne remplace e-means sans preuve : ``compare`` mesure la stabilité (indice de Rand
ajusté entre graines), l'accord avec les étiquettes (information mutuelle normalisée) et
le regroupement des paires du banc d'essai, pour les deux méthodes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

COMMUNITIES_DIR = "communities"
MIN_SIZE = 5          # en dessous, une communauté est rattachée à sa voisine la plus liée


# ------------------------------------------------------------------ graphe
def knn_graph(X: np.ndarray, k: int = 15):
    """Graphe non orienté des k plus proches voisines, pondéré par la similarité cosinus
    (``X`` normalisé). Une arête A–B existe si B est voisine de A *ou* l'inverse."""
    import igraph as ig

    from .layout import neighbors

    rows, scores = neighbors(X, k)
    n = len(X)
    src = np.repeat(np.arange(n), rows.shape[1])
    dst, w = rows.ravel(), np.clip(scores.ravel(), 1e-4, None)
    keep = dst >= 0
    src, dst, w = src[keep], dst[keep], w[keep]
    a, b = np.minimum(src, dst), np.maximum(src, dst)
    G = ig.Graph(n=n, edges=np.column_stack([a, b]).tolist(), directed=False)
    G.es["weight"] = w.astype(float).tolist()
    G.simplify(combine_edges="max")
    return G


def _leiden(G, resolution: float, seed: int, iterations: int = 2) -> np.ndarray:
    import leidenalg as la

    part = la.find_partition(G, la.RBConfigurationVertexPartition, weights="weight",
                             resolution_parameter=resolution, seed=seed, n_iterations=iterations)
    return np.asarray(part.membership, dtype=np.int32)


def merge_small(G, labels: np.ndarray, min_size: int = MIN_SIZE) -> np.ndarray:
    """Rattache chaque communauté trop petite, **entière**, à la communauté voisine avec laquelle
    elle partage le plus de poids d'arêtes (une grande de préférence), de la plus petite à la plus
    grande, en tenant les tailles à jour. Une petite communauté n'est donc jamais coupée entre deux
    groupes. Celles sans aucun lien restent seules. Puis renumérote 0..n-1."""
    import heapq

    labels = np.asarray(labels).copy()
    sizes = np.bincount(labels).astype(np.int64)
    if G.ecount() == 0 or (sizes >= min_size).all():
        _, labels = np.unique(labels, return_inverse=True)
        return labels.astype(np.int32)
    edges = np.asarray(G.get_edgelist(), dtype=np.int64)
    w = np.asarray(G.es["weight"] if "weight" in G.es.attributes() else np.ones(len(edges)), dtype=np.float64)
    la, lb = labels[edges[:, 0]], labels[edges[:, 1]]
    cross = la != lb
    # poids total entre deux communautés (graphe contracté), dans les deux sens
    W: dict[int, dict[int, float]] = {}
    for a, b, x in zip(la[cross].tolist(), lb[cross].tolist(), w[cross].tolist()):
        W.setdefault(a, {})[b] = W.setdefault(a, {}).get(b, 0.0) + x
        W.setdefault(b, {})[a] = W.setdefault(b, {}).get(a, 0.0) + x
    parent = np.arange(len(sizes))
    heap = [(int(sizes[c]), c) for c in np.flatnonzero((sizes > 0) & (sizes < min_size)).tolist()]
    heapq.heapify(heap)
    while heap:
        size, c = heapq.heappop(heap)
        if parent[c] != c or sizes[c] != size or sizes[c] >= min_size or not W.get(c):
            continue
        nb = W[c]
        big = {d: x for d, x in nb.items() if sizes[d] >= min_size}
        d = max(big or nb, key=(big or nb).get)
        parent[c] = d
        sizes[d] += sizes[c]
        sizes[c] = 0
        for e, x in nb.items():                  # les liens de c deviennent ceux de d
            del W[e][c]
            if e != d:
                W[d][e] = W[d].get(e, 0.0) + x
                W[e][d] = W[e].get(d, 0.0) + x
        del W[c]
        if sizes[d] < min_size:
            heapq.heappush(heap, (int(sizes[d]), d))

    def root(c: int) -> int:
        while parent[c] != c:
            parent[c] = parent[parent[c]]
            c = parent[c]
        return c

    roots = np.array([root(c) for c in range(len(sizes))])
    _, labels = np.unique(roots[labels], return_inverse=True)
    return labels.astype(np.int32)


def leiden_for_count(G, target: int, seed: int = 0, min_size: int = MIN_SIZE,
                     lo: float = 1e-3, hi: float = 1e3, steps: int = 14) -> tuple[np.ndarray, float]:
    """Cherche la résolution qui donne ≈ ``target`` groupes (après rattachement des petits).
    Recherche par dichotomie sur log γ : le nombre de groupes croît avec γ, sauf quand γ est si
    grand que Leiden émiette le graphe (plus de la moitié des œuvres dans des communautés de moins
    de ``min_size``) : leur rattachement fait alors *baisser* le compte, et l'on sait que γ est trop
    grand même si le compte paraît trop petit."""
    best, best_gap, best_g = None, None, None
    for _ in range(steps):
        g = float(np.sqrt(lo * hi))
        raw = _leiden(G, g, seed)
        raw_sizes = np.bincount(raw)
        crumbs = float(raw_sizes[raw_sizes < min_size].sum()) / max(len(raw), 1)
        labels = merge_small(G, raw, min_size)
        count = int(labels.max()) + 1
        gap = abs(count - target)
        if best is None or gap < best_gap:
            best, best_gap, best_g = labels, gap, g
        if count == target or gap <= max(1, target // 50):
            break
        if count < target and crumbs <= 0.5:
            lo = g
        else:
            hi = g
    return best, best_g


def families_of(G, groups: np.ndarray, target: int, seed: int = 0, X: np.ndarray | None = None) -> np.ndarray:
    """Familles = Leiden sur le graphe des groupes (poids = somme des arêtes entre deux
    groupes). Une famille est donc toujours une réunion de groupes. Un groupe sans aucun
    lien vers les autres (toutes ses voisines sont chez lui) est relié aux 3 groupes dont
    le centre est le plus proche, s'il a les vecteurs ``X``. Renvoie, pour chaque groupe,
    le numéro de sa famille."""
    import igraph as ig

    n = int(groups.max()) + 1
    H = G.copy()
    H.contract_vertices(groups.tolist(), combine_attrs=None)
    H.simplify(combine_edges="sum", loops=True)
    edges, weights = list(H.get_edgelist()), list(H.es["weight"]) if H.ecount() else []
    isolated = set(range(n)) - {v for e in edges for v in e}
    if isolated and X is not None and n > 1:
        cent = np.stack([X[groups == g].mean(axis=0) for g in range(n)])
        cent /= np.maximum(np.linalg.norm(cent, axis=1, keepdims=True), 1e-12)
        S = cent @ cent.T
        np.fill_diagonal(S, -np.inf)
        floor = min(weights) if weights else 1.0
        for g in isolated:
            for h in np.argsort(-S[g])[:min(3, n - 1)]:
                edges.append((g, int(h)))
                weights.append(floor * max(float(S[g, h]), 1e-3))
    H = ig.Graph(n=n, edges=edges, directed=False, edge_attrs={"weight": weights})
    H.simplify(combine_edges="sum")
    fam, _ = leiden_for_count(H, target, seed=seed, min_size=1)
    return fam


# ------------------------------------------------------------------ calcul
@dataclass
class Communities:
    space: str
    ids: np.ndarray        # (N,) identifiants d'œuvres
    groups: np.ndarray     # (N,) groupe de chaque œuvre
    families: np.ndarray   # (G,) famille de chaque groupe
    resolution: float
    params: dict


def compute(space: str, ids: np.ndarray, X: np.ndarray, n_groups: int, n_families: int,
            k: int = 15, seed: int = 0, say=print) -> Communities:
    import time

    t = time.time()
    G = knn_graph(X, k)
    say(f"  graphe : {G.vcount()} œuvres, {G.ecount()} liens ({time.time() - t:.0f} s)")
    t = time.time()
    groups, g = leiden_for_count(G, n_groups, seed=seed)
    fam = families_of(G, groups, n_families, seed=seed, X=X)
    say(f"  Leiden : {groups.max() + 1} groupes, {fam.max() + 1} familles, γ = {g:.3g} ({time.time() - t:.0f} s)")
    return Communities(space, ids, groups, fam, g, {"k": k, "seed": seed, "target_groups": n_groups,
                                                   "target_families": n_families, "min_size": MIN_SIZE})


def save(analysis, c: Communities) -> Path:
    d = Path(analysis.path) / COMMUNITIES_DIR
    d.mkdir(exist_ok=True)
    np.savez_compressed(d / f"{c.space}.npz", ids=c.ids, groups=c.groups, families=c.families)
    (d / f"{c.space}.json").write_text(json.dumps({
        "space": c.space, "method": "Leiden (RBConfiguration) sur le graphe des k plus proches voisines",
        "resolution": c.resolution, "n_groups": int(c.groups.max()) + 1, "n_families": int(c.families.max()) + 1,
        "params": c.params}, ensure_ascii=False, indent=1), encoding="utf-8")
    return d / f"{c.space}.npz"


def load(analysis, space: str) -> dict | None:
    p = Path(analysis.path) / COMMUNITIES_DIR / f"{space}.npz"
    if not p.exists():
        return None
    z = np.load(p)
    return {**json.loads(p.with_suffix(".json").read_text(encoding="utf-8")),
            "ids": z["ids"], "groups": z["groups"], "families": z["families"]}


def available(analysis) -> list[str]:
    d = Path(analysis.path) / COMMUNITIES_DIR
    return sorted(p.stem for p in d.glob("*.npz")) if d.exists() else []


# ------------------------------------------------------------------ comparaison
def label_agreement(labels: np.ndarray, meta_values: list[str]) -> float:
    """Information mutuelle normalisée entre des groupes et une étiquette (valeurs
    inconnues ignorées). 0 = indépendants, 1 = les groupes sont l'étiquette."""
    from sklearn.metrics import normalized_mutual_info_score

    v = np.array(meta_values, dtype=object)
    ok = np.array([bool(x) and not str(x).lower().startswith("unknown") for x in v])
    return float(normalized_mutual_info_score(v[ok], labels[ok])) if ok.sum() > 1 else float("nan")


def pair_lift(labels: np.ndarray, row: dict[int, int], pairs) -> dict[str, float]:
    """Pour chaque type de paire : P(les deux œuvres dans le même groupe), divisée par ce
    qu'on obtiendrait pour deux œuvres prises au hasard (Σ (taille / N)²). 1 = hasard."""
    sizes = np.bincount(labels)
    chance = float(((sizes / sizes.sum()) ** 2).sum())
    out: dict[str, list[bool]] = {}
    for p in pairs:
        if p.a in row and p.b in row:
            out.setdefault(p.type, []).append(labels[row[p.a]] == labels[row[p.b]])
    return {t: float(np.mean(v)) / chance for t, v in out.items()}


def size_stats(labels: np.ndarray) -> dict:
    s = np.bincount(labels)
    return {"n": int(len(s)), "min": int(s.min()), "median": int(np.median(s)), "max": int(s.max()),
            "largest_share": round(float(s.max() / s.sum()), 4)}
