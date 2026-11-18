"""Banc d'essai « composition » : quel regard retrouve une œuvre qui reprend la disposition
d'une autre (même composition, sujet ou manière différents) ?

Étape 0.15 de la feuille de route. On compare, sur les paires validées par l'utilisateur
(``pairbench``), les regards existants et deux familles de candidats :

- **vecteur global** d'un modèle (PE-Spatial : moyenne de ses vecteurs de patchs) ;
- **vecteur de disposition 4 × 4** : l'œuvre découpée en 16 cases ; chaque case est résumée
  par la moyenne de ses patchs (déjà calculée par l'extraction : ``regions.npy``), ramenée à
  la longueur 1, et les 16 cases sont mises bout à bout. Deux œuvres sont proches si chaque
  case ressemble à la case **au même endroit** dans l'autre : c'est « ce qui est représenté,
  et où ». Calculé pour DINOv3 et pour PE-Spatial.

Les rangs sont exacts, sur tout le corpus, comme dans ``pairbench``.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import numpy as np

from ..features.extract import OK
from ..features.regions import DEFAULT_GRIDS
from .pairbench import Pair, PairResult

# position des 16 cases 4 × 4 dans regions.npy (grilles 1, 2, 4 : 1 + 4 cases avant)
_START = sum(g * g for g in DEFAULT_GRIDS if g < 4)
CELLS = slice(_START, _START + 16)


def layout(regions: np.ndarray) -> np.ndarray:
    """(n, régions, D) → (n, 16·D) : cases 4 × 4 normalisées une à une, mises bout à bout,
    le tout de longueur 1 (le produit scalaire vaut la moyenne des 16 cosinus case à case)."""
    cells = np.asarray(regions[:, CELLS, :], dtype=np.float32)
    cells /= np.maximum(np.linalg.norm(cells, axis=2, keepdims=True), 1e-6)
    return cells.reshape(len(cells), -1) / 4.0


def layout_rows(run_path: Path, ids: list[int]) -> tuple[np.ndarray, dict[int, int]]:
    """Lignes de ``regions.npy`` des œuvres données (celles que le run a bien traitées)."""
    run_ids = np.load(run_path / "ids.npy")
    status = np.load(run_path / "status.npy", mmap_mode="r")
    where = {int(i): r for r, i in enumerate(run_ids) if status[r] == OK}
    present = [i for i in ids if i in where]
    return np.array([where[i] for i in present]), {i: n for n, i in enumerate(present)}


def _cells(regions: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Cases 4 × 4 normalisées (n, 16, D) et masque des cases non vides (n, 16) : une case qui
    tombe entièrement dans les bandes ajoutées autour de l'œuvre vaut zéro à l'extraction."""
    cells = np.asarray(regions[:, CELLS, :], dtype=np.float32)
    norm = np.linalg.norm(cells, axis=2)
    cells /= np.maximum(norm, 1e-6)[..., None]
    return cells, (norm > 1e-6).astype(np.float32)


def _block(kind: str, R, rows):
    """Ce qui est comparé pour un bloc d'œuvres, selon la variante."""
    if kind == "global_masque":                   # moyenne des patchs de l'œuvre seule (région 1 × 1)
        g = np.asarray(R[rows, 0, :], dtype=np.float32)
        return g / np.maximum(np.linalg.norm(g, axis=1, keepdims=True), 1e-6), None
    cells, mask = _cells(R[rows])
    return cells.reshape(len(rows), -1), mask


def similarities(kind: str, qa_block, b_block) -> np.ndarray:
    """``layout`` : moyenne des 16 cosinus case à case (une case vide compte 0) ;
    ``layout_communes`` : moyenne sur les seules cases remplies dans les DEUX œuvres (deux œuvres de
    proportions différentes ne sont plus pénalisées) ; ``global_masque`` : cosinus des vecteurs globaux."""
    (Q, mq), (B, mb) = qa_block, b_block
    dot = Q @ B.T
    if kind == "global_masque":
        return dot
    if kind == "layout":
        return dot / 16.0
    return dot / np.maximum(mq @ mb.T, 1.0)


def layout_ranks(run_path: Path, rows: np.ndarray, qa: np.ndarray, qb: np.ndarray,
                 kind: str = "layout", chunk: int = 4096) -> np.ndarray:
    """Rang de ``qb[n]`` parmi les voisines de ``qa[n]`` (indices dans ``rows``), sur tout le
    corpus, la requête exclue, ex aequo comptés au meilleur rang (comme ``pairbench``). Calcul
    exact, par morceaux (les vecteurs de disposition de 80 000 œuvres ne tiennent pas en mémoire)."""
    R = np.load(run_path / "regions.npy", mmap_mode="r")
    Q = _block(kind, R, rows[qa])
    S = np.empty((len(qa), len(rows)), dtype=np.float32)
    order = np.argsort(rows)                            # lecture du disque dans l'ordre
    for s in range(0, len(rows), chunk):
        part = order[s:s + chunk]
        S[:, part] = similarities(kind, Q, _block(kind, R, rows[part]))
    target = S[np.arange(len(qa)), qb][:, None]
    S[np.arange(len(qa)), qa] = -np.inf
    return (S > target).sum(axis=1) + 1


def aggregate(space: str, usable: list[Pair], ranks: np.ndarray, n_corpus: int) -> list[PairResult]:
    """Mêmes mesures que ``pairbench.score_pairs`` (2 requêtes par paire : a → b et b → a)."""
    half = len(usable)
    groups = defaultdict(list)
    for n, p in enumerate(usable):
        groups[(p.type, p.origin)] += [ranks[n], ranks[n + half]]
    out = []
    for (t, origin), rs in sorted(groups.items()):
        rs = np.array(rs)
        out.append(PairResult(space, t, origin, len(rs), float((rs <= 10).mean()), float((rs <= 100).mean()),
                              float(np.median(rs)), float(1 - ((rs - 1) / max(n_corpus - 2, 1)).mean())))
    return out


def score_layout(space: str, run_path: Path, pairs: list[Pair], ids: list[int],
                 kind: str = "layout") -> list[PairResult]:
    import json
    grids = json.loads((run_path / "manifest.json").read_text(encoding="utf-8"))["params"].get("region_grids")
    if grids is not None and tuple(grids) != tuple(DEFAULT_GRIDS):
        raise ValueError(f"{run_path.name} : grilles {grids}, attendu {DEFAULT_GRIDS}")
    rows, row = layout_rows(run_path, ids)
    usable = [p for p in pairs if p.status == "validée" and p.a in row and p.b in row]
    if not usable:
        return []
    qa = np.array([row[p.a] for p in usable] + [row[p.b] for p in usable])
    qb = np.array([row[p.b] for p in usable] + [row[p.a] for p in usable])
    return aggregate(space, usable, layout_ranks(run_path, rows, qa, qb, kind), len(rows))
