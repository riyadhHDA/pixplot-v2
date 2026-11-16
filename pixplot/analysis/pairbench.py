"""Banc d'essai par paires : quel regard retrouve quelle sorte de ressemblance ?

Les scores par étiquette (``bench.py``) disent si les voisines partagent l'artiste ou le
style. Ils ne disent pas *pourquoi* deux œuvres se ressemblent. Ici, chaque paire porte un
**type de ressemblance** (même sujet mais autre composition, même facture mais autres
artistes…) et l'on mesure, dans chaque regard, à quel rang l'une des œuvres retrouve
l'autre parmi tout le corpus.

Deux origines de paires, toujours séparées dans le rapport :

- **annotées** : choisies par un historien (Atlas, ``pixplot pairs add``), avec leur source
  (« Honour et Fleming, p. 670 »). Seules les paires ``validée`` comptent ; les
  ``proposée`` attendent une relecture.
- **métadonnées** : tirées au hasard d'après les étiquettes du catalogue (même genre et
  styles différents, etc.). Nombreuses mais grossières : une étiquette n'est pas un
  regard d'historien, et les étiquettes WikiArt sont parfois fausses.

Mesures, pour chaque paire prise dans les deux sens (A cherche B, B cherche A) :
``R@10`` et ``R@100`` (B parmi les 10 / 100 plus proches de A), rang médian, et
**centile** : part du corpus plus éloignée de A que B (0,5 = hasard, 1 = la plus proche).
Le centile est la bonne mesure pour les paires « métadonnées » : deux œuvres prises au
hasard dans le même style ne seront presque jamais voisines directes.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# clé → (libellé, regard attendu, question posée)
TYPES: dict[str, tuple[str, str | None, str]] = {
    "meme_sujet": ("Même sujet, composition différente", "sujet",
                   "le regard reconnaît-il un sujet sous des mises en page différentes ?"),
    "meme_composition": ("Même composition, sujet différent", "forme",
                         "le regard voit-il une mise en page commune à deux sujets ?"),
    "meme_main": ("Même artiste, facture différente", None,
                  "reconnaît-on une main d'une manière à l'autre ?"),
    "meme_facture": ("Artistes différents, facture comparable", "touche",
                     "le regard voit-il la facture plutôt que l'artiste ou le sujet ?"),
    "meme_motif": ("Même motif iconographique, époque différente", "sujet",
                   "un motif traverse-t-il les époques dans ce regard ?"),
    "meme_palette": ("Même palette, traditions différentes", "couleur",
                     "le regard rapproche-t-il des palettes au-delà des écoles ?"),
    "filiation": ("Filiation attestée (copie, citation, modèle)", None,
                  "le regard retrouve-t-il un lien établi par les historiens ?"),
    "temoin": ("Témoin : ni artiste, ni style, ni genre communs", None,
               "niveau de base : ce que le regard donne sans ressemblance attendue"),
}
STATUSES = ("validée", "proposée", "rejetée")
FIELDS = ["a", "b", "type", "origin", "status", "source", "note"]
PAIRS_FILE = "pairs.csv"

# Styles WikiArt définis d'abord par la facture (la façon de poser la couleur).
FACTURE_STYLES = ["Pointillism", "Fauvism", "Ukiyo_e", "Action_painting", "Analytical_Cubism", "Impressionism"]
FIGURATIVE_GENRES = ["portrait", "landscape", "genre_painting", "religious_painting", "cityscape",
                     "still_life", "nude_painting"]


@dataclass
class Pair:
    a: int
    b: int
    type: str
    origin: str = "annotée"
    status: str = "validée"
    source: str = ""
    note: str = ""


def pairs_path(settings) -> Path:
    return Path(settings.data_dir) / "bench" / PAIRS_FILE


def load_pairs(path: Path) -> list[Pair]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return [Pair(int(r["a"]), int(r["b"]), r["type"], r.get("origin") or "annotée",
                     r.get("status") or "validée", r.get("source") or "", r.get("note") or "")
                for r in csv.DictReader(f)]


def save_pairs(path: Path, pairs: list[Pair]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for p in pairs:
            w.writerow({k: getattr(p, k) for k in FIELDS})


def _key(a: int, b: int, t: str) -> tuple:
    return (min(a, b), max(a, b), t)


def add_pair(path: Path, pair: Pair) -> Pair:
    """Ajoute (ou met à jour) une paire. Une paire est la même quel que soit l'ordre A/B."""
    if pair.type not in TYPES:
        raise ValueError(f"Type inconnu : {pair.type} (types : {', '.join(TYPES)})")
    if pair.status not in STATUSES:
        raise ValueError(f"Statut inconnu : {pair.status} ({', '.join(STATUSES)})")
    if pair.a == pair.b:
        raise ValueError("Une paire relie deux œuvres différentes")
    pairs = [p for p in load_pairs(path) if _key(p.a, p.b, p.type) != _key(pair.a, pair.b, pair.type)]
    pairs.append(pair)
    save_pairs(path, pairs)
    return pair


# ------------------------------------------------------------------ paires des métadonnées
def _known(v: str | None) -> bool:
    return bool(v) and not v.lower().startswith("unknown")


def metadata_pairs(meta: dict[int, dict], n: int = 300, seed: int = 0) -> list[Pair]:
    """Paires tirées des étiquettes. Chaque type a ses contraintes, pour que la ressemblance
    attendue soit la seule commune (par ex. même facture : artistes ET genres différents)."""
    rng = np.random.default_rng(seed)
    ids = np.array(sorted(meta))
    A = np.array([meta[i].get("artist", "") for i in ids], dtype=object)
    S = np.array([meta[i].get("style", "") for i in ids], dtype=object)
    G = np.array([meta[i].get("genre", "") for i in ids], dtype=object)
    known_g = np.array([_known(g) for g in G])
    known_s = np.array([_known(s) for s in S])
    out: list[Pair] = []

    seen: set = set()

    def draw(t: str, pool_a: np.ndarray, ok, src: str, tries: int = 60, n: int = n, note=None) -> None:
        got = 0
        if len(pool_a) == 0:
            return
        for _ in range(n * tries):
            if got >= n:
                break
            i = int(rng.choice(pool_a))
            cands = ok(i)
            if len(cands) == 0:
                continue
            j = int(rng.choice(cands))
            k = _key(int(ids[i]), int(ids[j]), t)
            if k in seen:
                continue
            seen.add(k)
            out.append(Pair(int(ids[i]), int(ids[j]), t, "métadonnées", "validée", src,
                            note(i) if note else ""))
            got += 1

    by_genre = {g: np.flatnonzero(G == g) for g in FIGURATIVE_GENRES}
    fig = np.flatnonzero(np.isin(G, FIGURATIVE_GENRES) & known_s)
    draw("meme_sujet", fig, lambda i: by_genre[G[i]][(A[by_genre[G[i]]] != A[i]) & (S[by_genre[G[i]]] != S[i])
                                                     & known_s[by_genre[G[i]]]],
         "même genre, artistes et styles différents")

    by_artist = defaultdict(list)
    for r, a in enumerate(A):
        if _known(a) and known_s[r]:
            by_artist[a].append(r)
    by_artist = {a: np.array(r) for a, r in by_artist.items() if len(set(S[r])) > 1}
    pool = np.concatenate(list(by_artist.values())) if by_artist else np.array([], dtype=int)
    draw("meme_main", pool, lambda i: by_artist[A[i]][S[by_artist[A[i]]] != S[i]],
         "même artiste, styles différents")

    # à parts égales entre les styles, sinon l'impressionnisme (13 000 œuvres) dominerait
    for style in FACTURE_STYLES:
        members = np.flatnonzero((S == style) & known_g)
        draw("meme_facture", members, lambda i, m=members: m[(A[m] != A[i]) & (G[m] != G[i])],
             "même style de facture, artistes et genres différents",
             n=max(1, n // len(FACTURE_STYLES)), note=lambda i, st=style: st)

    base = np.flatnonzero(known_g & known_s)
    draw("temoin", base, lambda i: (lambda c: c[rng.integers(len(c), size=min(len(c), 50))])(
        base[(A[base] != A[i]) & (S[base] != S[i]) & (G[base] != G[i])]),
        "artistes, styles et genres différents")
    return out


# ------------------------------------------------------------------ mesure
@dataclass
class PairResult:
    space: str
    type: str
    origin: str
    n: int          # nombre de requêtes (2 par paire)
    r10: float
    r100: float
    median_rank: float
    centile: float


def ranks_in_space(X: np.ndarray, rows_a: np.ndarray, rows_b: np.ndarray, chunk: int = 256) -> np.ndarray:
    """Rang (1 = la plus proche) de ``rows_b[n]`` parmi les voisines de ``rows_a[n]``, sur
    tout ``X`` (lignes normalisées), la requête elle-même exclue. Calcul exact."""
    out = np.empty(len(rows_a), dtype=np.int64)
    for s in range(0, len(rows_a), chunk):
        qa, qb = rows_a[s:s + chunk], rows_b[s:s + chunk]
        Sim = X[qa] @ X.T                                   # (m, N)
        target = Sim[np.arange(len(qa)), qb][:, None]
        Sim[np.arange(len(qa)), qa] = -np.inf               # la requête elle-même
        out[s:s + chunk] = (Sim > target).sum(axis=1) + 1
    return out


def score_pairs(pairs: list[Pair], spaces: dict[str, tuple[np.ndarray, dict[int, int]]],
                include_proposed: bool = False) -> tuple[list[PairResult], dict]:
    """``spaces`` : regard → (vecteurs normalisés, id → ligne). Renvoie les résultats agrégés
    et, pour chaque paire, ses rangs par regard (pour l'Atlas et l'export)."""
    keep = [p for p in pairs if p.status == "validée" or (include_proposed and p.status == "proposée")]
    results, detail = [], defaultdict(dict)
    for space, (X, row) in spaces.items():
        N = len(X)
        usable = [p for p in keep if p.a in row and p.b in row]
        if not usable:
            continue
        ra = np.array([row[p.a] for p in usable] + [row[p.b] for p in usable])
        rb = np.array([row[p.b] for p in usable] + [row[p.a] for p in usable])
        ranks = ranks_in_space(X, ra, rb)
        half = len(usable)
        for n, p in enumerate(usable):
            detail[_key(p.a, p.b, p.type)][space] = (int(ranks[n]), int(ranks[n + half]))
        groups = defaultdict(list)
        for n, p in enumerate(usable):
            for r in (ranks[n], ranks[n + half]):
                groups[(p.type, p.origin)].append(r)
        for (t, origin), rs in sorted(groups.items()):
            rs = np.array(rs)
            results.append(PairResult(space, t, origin, len(rs), float((rs <= 10).mean()),
                                      float((rs <= 100).mean()), float(np.median(rs)),
                                      float(1 - ((rs - 1) / max(N - 2, 1)).mean())))
    return results, dict(detail)


def load_space_matrix(spaces_obj, key: str, ids: list[int]) -> tuple[np.ndarray, dict[int, int]]:
    """Vecteurs normalisés d'un regard pour les œuvres données (celles qu'il connaît)."""
    spaces_obj._open(key)
    known = spaces_obj._rows[key]
    present = [i for i in ids if i in known]
    X = spaces_obj.vectors(key, present)
    return np.ascontiguousarray(X), {i: r for r, i in enumerate(present)}
