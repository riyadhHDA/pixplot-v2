"""Constituer une sélection d'œuvres pour un Research Pack, et garder trace de comment.

Partagé par la CLI (``pixplot pack``), l'API et le serveur MCP.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Selection:
    ids: list[int]
    how: dict
    scores: dict[int, float] = field(default_factory=dict)
    details: dict[int, list[float]] = field(default_factory=dict)


def by_ids(data, ids: list[int]) -> Selection:
    ids = [int(i) for i in ids if int(i) in data.row_of]
    return Selection(ids, {"méthode": "sélection manuelle", "œuvres": len(ids)})


def by_cluster(data, number: int, k: int | None = None) -> Selection:
    """Les œuvres d'un groupe e-means, les plus centrales d'abord."""
    c = number - 1
    rows = np.flatnonzero(data.clusters == c)
    if not len(rows):
        raise ValueError(f"Groupe {number} inexistant")
    rows = rows[np.argsort(data.atypicality[rows])]
    if k:
        rows = rows[:k]
    return Selection([int(data.ids[r]) for r in rows],
                     {"méthode": f"groupe {number} de l'analyse (les plus centrales d'abord)",
                      "taille du groupe": int((data.clusters == c).sum()), "œuvres retenues": len(rows)})


def by_similar(data, artwork_id: int, k: int = 30) -> Selection:
    r = data.row_of.get(artwork_id)
    if r is None:
        raise ValueError(f"Œuvre {artwork_id} absente de l'analyse")
    neigh = [(int(i), float(s)) for i, s in zip(data.neighbors[r][:k], data.neighbor_scores[r][:k]) if i >= 0]
    return Selection([artwork_id] + [i for i, _ in neigh],
                     {"méthode": f"œuvre {artwork_id} et ses {len(neigh)} plus proches voisines (DINOv3)",
                      "œuvre de départ": data.label(artwork_id)},
                     scores={i: round(s, 4) for i, s in neigh})


def by_text(engines, query: str, k: int = 30) -> Selection:
    res = engines.text(query, k=k)
    return Selection([x["id"] for x in res["results"]],
                     {"méthode": "recherche en texte libre (SigLIP 2)", "requête": query,
                      "vecteurs": res["features"]},
                     scores={x["id"]: x["score"] for x in res["results"]})


def by_detail(engines, artwork_id: int, box, k: int = 30) -> Selection:
    res = engines.region(artwork_id, box, k=k)
    ids = [artwork_id] + [x["id"] for x in res["results"]]
    details = {artwork_id: list(box)}
    details.update({x["id"]: x["box"] for x in res["results"] if x.get("box")})
    return Selection(ids, {"méthode": "recherche par détail (zones DINOv3)",
                           "œuvre et cadre de départ": f"{artwork_id}, cadre {[round(v, 3) for v in box]}",
                           "index": res["index"]},
                     scores={x["id"]: x["score"] for x in res["results"]}, details=details)
