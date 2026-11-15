"""Compare des runs de vecteurs avec les étiquettes du catalogue (artiste, style, genre...).

Pour chaque œuvre ayant l'étiquette, on regarde ses k plus proches voisines et on mesure :
  P@1  : la plus proche a-t-elle la même étiquette ?
  P@k  : part des k plus proches qui partagent l'étiquette.
Les valeurs « inconnues » (Unknown ...) sont ignorées, comme requêtes et comme cibles.
Le hasard donne environ la fréquence moyenne de l'étiquette (colonne « hasard »).

Usage :
    python scripts/eval_labels.py [--k 10] [--keys artist,style,genre] RUN [RUN ...]
    (RUN = nom du dossier dans data/runs/features, ex. dinov3_vitb16_20261115-221500)
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

import numpy as np

from pixplot.catalog import db
from pixplot.catalog.metadata import get_metadata
from pixplot.config import get_settings
from pixplot.features.extract import OK
from pixplot.runs import Run


def evaluate(run: Run, conn, keys: list[str], k: int) -> dict[str, tuple[float, float, float, int]]:
    ids = np.load(run.path / "ids.npy")
    status = np.load(run.path / "status.npy")
    keep = status == OK
    ids = ids[keep]
    X = np.load(run.path / "global.npy")[keep].astype(np.float32)
    S = X @ X.T
    np.fill_diagonal(S, -np.inf)
    nn = np.argsort(-S, axis=1)[:, :k]
    meta = get_metadata(conn, ids.tolist())

    out = {}
    for key in keys:
        labels = np.array([meta[int(i)].get(key) or "" for i in ids], dtype=object)
        valid = np.array([bool(l) and not l.lower().startswith("unknown") for l in labels])
        if valid.sum() < 2:
            continue
        p1, pk = [], []
        for q in np.flatnonzero(valid):
            neigh = [j for j in nn[q] if valid[j]]
            if not neigh:
                continue
            same = labels[neigh] == labels[q]
            p1.append(float(same[0]))
            pk.append(float(same.mean()))
        counts = Counter(labels[valid])
        n = valid.sum()
        chance = sum((c / n) ** 2 for c in counts.values())
        out[key] = (float(np.mean(p1)), float(np.mean(pk)), chance, int(n))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--keys", default="artist,style,genre")
    ap.add_argument("--data")
    a = ap.parse_args()
    s = get_settings(a.data)
    conn = db.connect(s.catalog_path)
    keys = a.keys.split(",")

    print(f"{'run':<42} {'étiquette':<8} {'P@1':>6} {f'P@{a.k}':>6} {'hasard':>7} {'n':>6}")
    for name in a.runs:
        run = Run.load(s.runs_dir / "features" / name)
        for key, (p1, pk, chance, n) in evaluate(run, conn, keys, a.k).items():
            print(f"{name:<42} {key:<8} {p1:>6.1%} {pk:>6.1%} {chance:>7.1%} {n:>6}")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
