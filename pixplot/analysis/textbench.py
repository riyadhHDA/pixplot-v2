"""Banc d'essai de la recherche par phrase, avec les descriptions de MMArt comme requêtes.

MMArt (Wang et al., 2026, CC BY 4.0) donne, pour chaque œuvre rattachée (``pixplot wikiart-noms``),
quatre descriptions écrites par un modèle de langage : narrative, formelle, émotionnelle, historique,
et une synthèse. On s'en sert ici comme de **requêtes** : la recherche par phrase retrouve-t-elle,
parmi toutes les œuvres, celle que la description décrit ? Rang exact de l'œuvre attendue, R@1, R@10,
R@100. Le titre lisible (« Portrait of a woman ») sert de requête témoin.

Les descriptions ne sont jamais une source sur les œuvres : un modèle de langage peut inventer (des
« figures qui dansent » dans une abstraction). Elles servent seulement de banc d'essai.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np

FIELDS = ("e_formal", "e_narrative", "e_emotional", "e_historical", "e_unified", "title")
LABELS = {"e_formal": "description formelle", "e_narrative": "description narrative",
          "e_emotional": "description émotionnelle", "e_historical": "description historique",
          "e_unified": "synthèse", "title": "titre (témoin)"}


def load_queries(conn, text_parquet: Path, n: int, seed: int = 0) -> list[dict]:
    """``n`` œuvres rattachées tirées au sort, avec leurs descriptions MMArt et leur titre."""
    import pyarrow.parquet as pq

    from ..catalog.wikiart_names import split_image_id

    files = dict(conn.execute("SELECT value, artwork_id FROM metadata WHERE key = 'wikiart_file'").fetchall())
    titles = dict(conn.execute("SELECT artwork_id, value FROM metadata WHERE key = 'title'").fetchall())
    cols = ["image_id"] + [f for f in FIELDS if f != "title"]
    out = []
    for r in pq.read_table(text_parquet, columns=cols).to_pylist():
        style, _, stem = split_image_id(r["image_id"])
        aid = files.get(f"{style}/{stem}")
        if aid is None or not titles.get(aid):
            continue
        out.append({"id": int(aid), "title": titles[aid], **{f: r[f] or "" for f in cols[1:]}})
    rng = np.random.default_rng(seed)
    pick = rng.choice(len(out), min(n, len(out)), replace=False)
    return [out[i] for i in sorted(pick)]


def ranks(image_vecs: np.ndarray, image_ids: np.ndarray, text_vecs: np.ndarray, targets: list[int],
          block: int = 256) -> np.ndarray:
    """Rang (1 = premier) de l'œuvre attendue pour chaque requête, sur tout le corpus."""
    row = {int(i): r for r, i in enumerate(image_ids)}
    out = np.full(len(targets), -1, dtype=np.int64)
    for s in range(0, len(targets), block):
        S = text_vecs[s:s + block] @ image_vecs.T            # (b, N)
        for k, t in enumerate(targets[s:s + block]):
            r = row.get(int(t))
            if r is not None:
                out[s + k] = int((S[k] > S[k, r]).sum()) + 1
    return out


def summary(r: np.ndarray) -> dict:
    r = r[r > 0]
    return {"n": int(len(r)), "R@1": round(float(np.mean(r <= 1)), 4), "R@10": round(float(np.mean(r <= 10)), 4),
            "R@100": round(float(np.mean(r <= 100)), 4), "median": int(np.median(r)) if len(r) else -1}


def run(features_run, queries: list[dict], device: str = "cpu", batch: int = 32,
        say: Callable[[str], None] = print) -> dict:
    """Encode chaque champ de chaque requête avec l'encodeur texte du run, et mesure les rangs."""
    from ..encoders.registry import get_encoder
    from .layout import load_valid

    p = features_run.manifest["params"]
    enc = get_encoder(p["encoder"], hf_model=p.get("weights"), input_size=p.get("input_size"), device=device)
    ids, X = load_valid(features_run)
    targets = [q["id"] for q in queries]
    res = {}
    for field in FIELDS:
        texts = [q[field] for q in queries]
        vecs = np.concatenate([enc.encode_text(texts[s:s + batch]) for s in range(0, len(texts), batch)])
        res[field] = summary(ranks(X, ids, vecs.astype(np.float32), targets))
        say(f"  {LABELS[field]:<26} {res[field]}")
    return res
