"""Doublons et variantes : les œuvres que SSCD (détection de copies, ARCHITECTURE § 27) juge
quasi identiques.

SSCD n'a pas été retenu comme regard (il retrouve moins bien les filiations que Forme et Sujet),
mais il est fait pour ce qu'on lui demande ici : reconnaître la même image malgré un recadrage, un
autre éclairage ou une autre numérisation. Deux niveaux, choisis en regardant des paires de
WikiArt 81k par tranche de cosinus (19/11/2026) :

- **même image** (cosinus ≥ 0,85) : deux reproductions d'une même œuvre, entrées deux fois dans le
  catalogue (le hachage de ``pixplot ingest`` ne voit que les fichiers identiques octet pour octet) ;
- **variante** (0,65 ≤ cosinus < 0,85) : répliques, séries (les cathédrales de Monet), états d'une
  gravure, copies anciennes… et parfois encore la même image, mal reproduite.

Pour chaque paire, on note les étiquettes du catalogue qui se contredisent (artiste, style,
genre, date) : c'est là que le catalogue se trompe le plus visiblement. Une paire est une piste,
pas un verdict : deux tableaux d'une série sont deux œuvres.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import numpy as np

FILE = "doublons.json"
SAME, VARIANT = 0.85, 0.65
KEYS = ("artist", "style", "genre", "date")
LEVELS = {"same": "même image", "variant": "variante"}


def find_sscd_run(runs_dir: Path | None):
    """Le dernier run de vecteurs SSCD complet (sans ``--limit``), ou None."""
    from ..runs import list_runs

    runs = [r for r in list_runs("features", runs_dir=runs_dir)
            if r.manifest["params"].get("encoder", "").startswith("sscd_")
            and r.manifest.get("status") == "complete" and not r.manifest["params"].get("limit")]
    return runs[-1] if runs else None


def _known(v) -> bool:
    return bool(v) and not str(v).lower().startswith("unknown")


def label_check(ma: dict, mb: dict) -> tuple[list[str], list[str]]:
    """(étiquettes qui se contredisent, étiquettes connues d'un seul côté)."""
    conflicts, one_side = [], []
    for k in KEYS:
        a, b = ma.get(k), mb.get(k)
        if _known(a) and _known(b):
            if str(a).strip().lower() != str(b).strip().lower():
                conflicts.append(k)
        elif _known(a) or _known(b):
            one_side.append(k)
    return conflicts, one_side


def compute(ids: np.ndarray, sscd_run, meta: dict[int, dict], k: int = 5, same: float = SAME,
            variant: float = VARIANT, say: Callable[[str], None] = print) -> dict:
    """Paires (a < b) dont le cosinus SSCD centré dépasse ``variant``, parmi les ``k`` plus
    proches voisines de chaque œuvre de l'analyse."""
    import faiss

    from .layout import load_valid

    fids, X = load_valid(sscd_run)
    row = {int(i): r for r, i in enumerate(fids)}
    keep = np.array([int(i) in row for i in ids])
    aids = np.asarray(ids)[keep].astype(np.int64)
    X = X[[row[int(i)] for i in aids]]
    X -= X.mean(axis=0)                                  # centrage conseillé par les auteurs de SSCD
    X /= np.maximum(np.linalg.norm(X, axis=1, keepdims=True), 1e-12)
    say(f"  {len(aids)} œuvres, {k} voisines chacune (SSCD centré)")
    index = faiss.IndexFlatIP(X.shape[1])
    index.add(X)
    found: dict[tuple[int, int], float] = {}
    for s in range(0, len(X), 4096):
        sims, rows = index.search(X[s:s + 4096], k + 1)
        for q in range(len(rows)):
            for sim, r in zip(sims[q], rows[q]):
                a = s + q
                if r < 0 or r == a or sim < variant:
                    continue
                key = (min(a, int(r)), max(a, int(r)))
                found[key] = max(found.get(key, -1.0), float(sim))
    pairs = []
    for (ra, rb), sim in found.items():
        a, b = int(aids[ra]), int(aids[rb])
        conflicts, one_side = label_check(meta.get(a, {}), meta.get(b, {}))
        pairs.append({"a": a, "b": b, "cos": round(sim, 4), "level": "same" if sim >= same else "variant",
                      "conflicts": conflicts, "one_side": one_side})
    # d'abord la même image, et dans chaque niveau les étiquettes contradictoires en tête
    pairs.sort(key=lambda p: (p["level"] != "same", not p["conflicts"], -p["cos"]))
    counts = {lvl: sum(p["level"] == lvl for p in pairs) for lvl in LEVELS}
    counts["conflicts"] = sum(bool(p["conflicts"]) for p in pairs)
    say(f"  même image : {counts['same']} paires · variantes : {counts['variant']} · "
        f"étiquettes contradictoires : {counts['conflicts']}")
    return {"sscd": sscd_run.id, "same": same, "variant": variant, "k": k, "centered": True,
            "n": int(len(aids)), "counts": counts, "pairs": pairs}


def save(analysis, res: dict) -> Path:
    path = Path(analysis.path) / FILE
    path.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    return path


def load(analysis) -> dict | None:
    path = Path(analysis.path) / FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
