"""Banc d'essai « chercher une zone avec des mots », sur RichArt (ICMR 2026).

RichArt décrit des zones de tableaux avec des phrases tirées des catalogues de musées
(« The church tower of Amstelveen … is visible in the left background »). Chaque objet a un
nom court (« church tower »), une phrase et un ou plusieurs cadres. Licence CC BY-NC 4.0 :
usage local d'évaluation seulement, rien n'est redistribué.

Deux épreuves, pour chaque objet et deux sortes de requêtes (le nom court, la phrase) :

1. **Retrouver la zone dans tout le corpus** : la requête est comparée à toutes les zones
   annotées de la partie test ; on regarde le rang de la meilleure zone de cet objet
   (R@1, R@5, R@10, rang médian).
2. **Pointer** : dans son propre tableau, la zone de 14 px la plus proche de la requête
   tombe-t-elle dans un des cadres de l'objet ? Comparé au hasard (part de la surface du
   tableau couverte par ces cadres).

Méthodes comparées :

- ``siglip2_crop`` : SigLIP 2 sur la zone découpée (ce que permettrait PixPlot aujourd'hui) ;
- ``tipsv2_crop`` : TIPSv2 sur la zone découpée ;
- ``tipsv2_dense`` : TIPSv2 sur le tableau entier, une seule fois, puis moyenne des vecteurs
  de zones de 14 px à l'intérieur du cadre — c'est ce qu'un index à l'échelle du corpus
  peut faire sans découper chaque zone à l'avance.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image


@dataclass
class Region:
    painting: int
    entity: int          # indice de l'objet (nom + phrase) auquel appartient le cadre
    box: tuple[float, float, float, float]


def load_richart(root: Path, split: str = "test", min_side: int = 8):
    """Renvoie (tableaux, objets, cadres). Les cadres de moins de ``min_side`` px sont ignorés."""
    root = Path(root)
    data = json.loads((root / "annotations" / f"{split}.json").read_text(encoding="utf-8"))
    paintings, entities, regions = [], [], []
    for p in data:
        path = root / "data" / split / f"{p['id']}.png"
        if not path.exists():
            continue
        pi = len(paintings)
        paintings.append({"id": p["id"], "path": path, "w": p["width"], "h": p["height"]})
        for name, obj in (p.get("objects") or {}).items():
            boxes = [tuple(b[1]) for b in obj.get("bounding_boxes", [])
                     if b[1][2] - b[1][0] >= min_side and b[1][3] - b[1][1] >= min_side]
            if not boxes:
                continue
            ei = len(entities)
            entities.append({"painting": pi, "name": name, "phrase": obj.get("description") or name, "boxes": boxes})
            regions += [Region(pi, ei, b) for b in boxes]
    return paintings, entities, regions


def _scale_box(box, w, h, img_w, img_h):
    """Les cadres sont donnés dans la taille déclarée (``width``, ``height``) ; l'image peut
    avoir été enregistrée à une autre taille."""
    sx, sy = img_w / w, img_h / h
    return box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy


def crop_vectors(encoder, paintings, regions, batch: int = 32, say=print) -> np.ndarray:
    out, buf = [], []
    cache: dict[int, Image.Image] = {}
    for n, r in enumerate(regions):
        p = paintings[r.painting]
        if r.painting not in cache:
            cache.clear()
            cache[r.painting] = Image.open(p["path"]).convert("RGB")
        img = cache[r.painting]
        x1, y1, x2, y2 = _scale_box(r.box, p["w"], p["h"], *img.size)
        crop = img.crop((max(0, int(x1)), max(0, int(y1)), min(img.width, int(np.ceil(x2))), min(img.height, int(np.ceil(y2)))))
        buf.append(encoder.preprocess(crop)[0])
        if len(buf) == batch or n == len(regions) - 1:
            out.append(encoder.encode(np.stack(buf)).global_vectors)
            buf = []
    return np.concatenate(out)


def dense_grids(encoder, paintings, size: int = 672, say=print) -> list[tuple[np.ndarray, tuple]]:
    """Une passe par tableau : grille de vecteurs de zones et position de l'œuvre dans le carré."""
    out = []
    for n, p in enumerate(paintings):
        img = Image.open(p["path"]).convert("RGB")
        arr, box = encoder.preprocess(img, size)
        out.append((encoder.dense(arr[None])[0], box, img.size))
        if (n + 1) % 200 == 0:
            say(f"    {n + 1}/{len(paintings)} tableaux")
    return out


def _cells(box, p, img_size, lb_box, grid_side, size):
    """Indices (ligne, colonne) des zones de 14 px dont le centre tombe dans le cadre."""
    x1, y1, x2, y2 = _scale_box(box, p["w"], p["h"], *img_size)
    left, top, w, h = lb_box
    s = w / img_size[0]
    X1, Y1, X2, Y2 = left + x1 * s, top + y1 * s, left + x2 * s, top + y2 * s
    cell = size / grid_side
    centers = (np.arange(grid_side) + 0.5) * cell
    cols = np.flatnonzero((centers >= X1) & (centers <= X2))
    rows = np.flatnonzero((centers >= Y1) & (centers <= Y2))
    if len(cols) == 0:
        cols = np.array([min(grid_side - 1, int((X1 + X2) / 2 // cell))])
    if len(rows) == 0:
        rows = np.array([min(grid_side - 1, int((Y1 + Y2) / 2 // cell))])
    return rows, cols


def dense_region_vectors(grids, paintings, regions, size: int = 672) -> np.ndarray:
    out = []
    for r in regions:
        g, lb, img_size = grids[r.painting]
        rows, cols = _cells(r.box, paintings[r.painting], img_size, lb, g.shape[0], size)
        v = g[np.ix_(rows, cols)].reshape(-1, g.shape[-1]).mean(axis=0)
        out.append(v / max(np.linalg.norm(v), 1e-12))
    return np.stack(out)


def retrieval(Q: np.ndarray, G: np.ndarray, regions, entities) -> dict:
    """Rang (1 = premier) de la meilleure zone de chaque objet parmi toutes les zones."""
    S = Q @ G.T
    ent = np.array([r.entity for r in regions])
    ranks = []
    for e in range(len(entities)):
        own = S[e, ent == e].max()
        ranks.append(int((S[e] > own).sum()) + 1)
    r = np.array(ranks)
    return {"n": len(r), "gallery": len(regions), "R@1": float((r <= 1).mean()), "R@5": float((r <= 5).mean()),
            "R@10": float((r <= 10).mean()), "median_rank": float(np.median(r))}


def pointing(Q: np.ndarray, grids, paintings, entities, size: int = 672) -> dict:
    """La zone de 14 px la plus proche de la requête (dans l'œuvre, hors bandes) est-elle
    dans un des cadres de l'objet ? Hasard = part de la surface couverte par ces cadres."""
    hits, chance = [], []
    for e, ent in enumerate(entities):
        g, lb, img_size = grids[ent["painting"]]
        side = g.shape[0]
        left, top, w, h = lb
        cell = size / side
        centers = (np.arange(side) + 0.5) * cell
        inside_c = (centers >= left) & (centers <= left + w)
        inside_r = (centers >= top) & (centers <= top + h)
        mask_art = np.outer(inside_r, inside_c)
        target = np.zeros((side, side), dtype=bool)
        for b in ent["boxes"]:
            rows, cols = _cells(b, paintings[ent["painting"]], img_size, lb, side, size)
            target[np.ix_(rows, cols)] = True
        target &= mask_art
        s = g @ Q[e]
        s[~mask_art] = -np.inf
        hits.append(bool(target.ravel()[int(np.argmax(s))]))
        chance.append(target.sum() / max(mask_art.sum(), 1))
    return {"n": len(hits), "hit": float(np.mean(hits)), "chance": float(np.mean(chance))}


def run(root: Path, siglip=None, tips=None, dense_size: int = 672, say=print) -> dict:
    paintings, entities, regions = load_richart(root)
    say(f"RichArt (test) : {len(paintings)} tableaux, {len(entities)} objets, {len(regions)} cadres")
    names = [e["name"] for e in entities]
    phrases = [e["phrase"] for e in entities]
    res: dict = {"paintings": len(paintings), "entities": len(entities), "regions": len(regions), "methods": {}}
    if siglip is not None:
        say("SigLIP 2 sur les zones découpées…")
        G = crop_vectors(siglip, paintings, regions)
        res["methods"]["siglip2_crop"] = {
            "nom": retrieval(siglip.encode_text(names), G, regions, entities),
            "phrase": retrieval(siglip.encode_text(phrases), G, regions, entities)}
    if tips is not None:
        say("TIPSv2 sur les zones découpées…")
        G = crop_vectors(tips, paintings, regions)
        Qn, Qp = tips.encode_text(names), tips.encode_text(phrases)
        res["methods"]["tipsv2_crop"] = {"nom": retrieval(Qn, G, regions, entities),
                                         "phrase": retrieval(Qp, G, regions, entities)}
        say(f"TIPSv2 sur les tableaux entiers ({dense_size} px)…")
        grids = dense_grids(tips, paintings, dense_size, say)
        G = dense_region_vectors(grids, paintings, regions, dense_size)
        res["methods"]["tipsv2_dense"] = {
            "nom": {**retrieval(Qn, G, regions, entities), "pointing": pointing(Qn, grids, paintings, entities, dense_size)},
            "phrase": {**retrieval(Qp, G, regions, entities), "pointing": pointing(Qp, grids, paintings, entities, dense_size)}}
    return res
