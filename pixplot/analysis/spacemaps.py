"""Une carte par regard : la projection UMAP des mêmes œuvres dans chaque espace.

La carte principale (``coords.npy``) vient de l'espace de l'analyse (DINOv3, « forme »).
Ici, on calcule la même chose pour les autres espaces (sujet, couleur, touche) : les œuvres
y sont rangées selon un autre critère, ce qui fait apparaître d'autres voisinages. Les
groupes restent ceux de l'analyse, pour pouvoir suivre un groupe d'une carte à l'autre.

Sortie : ``maps/<espace>.npy`` (N, 2) dans le run d'analyse, aligné sur ``ids.npy`` ;
NaN pour une œuvre absente de l'espace.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import numpy as np

from .layout import layout_umap, reduce_pca

MAPS_DIR = "maps"


def compute_space_maps(analysis, settings, spaces: list[str] | None = None, force: bool = False,
                       say: Callable[[str], None] = print) -> dict[str, Path]:
    from ..api.spaces import describe_encoder
    from ..features.extract import OK
    from ..features.store import FeatureStore
    from ..runs import list_runs

    p = Path(analysis.path)
    ids = np.load(p / "ids.npy")
    params = analysis.manifest.get("params", {})
    main_parent = analysis.manifest.get("parent")
    runs = {}
    for run in list_runs("features", runs_dir=settings.runs_dir):
        if run.manifest.get("status") != "complete" or run.manifest["params"].get("limit"):
            continue
        key = describe_encoder(run.manifest["params"].get("encoder", ""))[0]
        if run.id != main_parent:
            runs[key] = run
    from ..runs import Run
    main_key = describe_encoder(Run.load(settings.runs_dir / main_parent).manifest["params"].get("encoder", ""))[0]
    wanted = [k for k in (spaces or list(runs)) if k in runs and k != main_key]

    out_dir = p / MAPS_DIR
    out_dir.mkdir(exist_ok=True)
    done: dict[str, Path] = {}
    for key in wanted:
        path = out_dir / f"{key}.npy"
        if path.exists() and not force:
            say(f"  {key} : déjà calculée")
            done[key] = path
            continue
        store = FeatureStore.open(runs[key])
        row = {int(i): r for r, i in enumerate(store.ids) if store.status[r] == OK}
        present = np.array([int(i) in row for i in ids])
        rows = [row[int(i)] for i in ids[present]]
        order = np.argsort(rows)  # lecture du memmap dans l'ordre du disque
        X = np.empty((len(rows), store.global_vectors.shape[1]), dtype=np.float32)
        X[order] = np.asarray(store.global_vectors[np.asarray(rows)[order]], dtype=np.float32)
        X /= np.maximum(np.linalg.norm(X, axis=1, keepdims=True), 1e-12)
        say(f"  {key} ({runs[key].id}) : PCA puis UMAP sur {len(rows)} œuvres…")
        coords = np.full((len(ids), 2), np.nan, dtype=np.float32)
        coords[present] = layout_umap(reduce_pca(X, params.get("pca_dims", 64)),
                                      params.get("umap_neighbors", 15), params.get("umap_min_dist", 0.1))
        np.save(path, coords)
        done[key] = path
    (out_dir / "maps.json").write_text(json.dumps(
        {k: {"features": runs[k].id, "file": f"{k}.npy"} for k in done}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    return done


def load_space_map(analysis, key: str) -> np.ndarray | None:
    path = Path(analysis.path) / MAPS_DIR / f"{key}.npy"
    return np.load(path) if path.exists() else None


def available_maps(analysis) -> list[str]:
    d = Path(analysis.path) / MAPS_DIR
    return sorted(p.stem for p in d.glob("*.npy")) if d.exists() else []
